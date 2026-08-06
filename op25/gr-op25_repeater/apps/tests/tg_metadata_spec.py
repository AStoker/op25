# Copyright 2026 OP25 Contributors
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

"""Durable talkgroup metadata: the store, the merge rules, and the endpoint."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import tg_metadata
import websocket_server
from tg_metadata import TalkgroupStore, db_path


def tags(**kw: Any) -> dict[str, Any]:
    """One tgid_tags entry with the decoder's defaults filled in."""
    entry = {'tag': '', 'configured': False, 'prio': 3,
             'last_seen': 0, 'last_freq': None, 'count': 0}
    entry.update(kw)
    return entry


class TestDbPath:
    def test_defaults_to_cwd(self) -> None:
        # cwd is the user's data directory (multi_rx resolves tgid_tags_file and
        # the whitelists against it too), so a bare filename is right.
        assert db_path(None) == 'op25_metadata.sqlite'

    def test_config_overrides_default(self) -> None:
        assert db_path({'terminal': {'metadata_db': '/data/tg.sqlite'}}) == '/data/tg.sqlite'

    def test_config_can_disable(self) -> None:
        assert db_path({'terminal': {'metadata_db': ''}}) is None
        assert db_path({'terminal': {'metadata_db': False}}) is None

    def test_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('OP25_METADATA_DB', '/tmp/env.sqlite')
        assert db_path({'terminal': {'metadata_db': '/data/tg.sqlite'}}) == '/tmp/env.sqlite'

    def test_env_can_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('OP25_METADATA_DB', '')
        assert db_path({'terminal': {'metadata_db': '/data/tg.sqlite'}}) is None


class TestObserve:
    def test_records_activity(self) -> None:
        store = TalkgroupStore(None)
        now = time.time()
        store.observe('sys', {'101': tags(tag='FIRE', last_seen=now, last_freq=851_000_000)})
        rows = store.talkgroups()
        assert len(rows) == 1
        assert rows[0]['tgid'] == 101
        assert rows[0]['tag'] == 'FIRE'
        assert rows[0]['last_seen'] == now
        assert rows[0]['last_freq'] == 851_000_000

    def test_never_heard_talkgroup_is_tracked_but_unstamped(self) -> None:
        """A tgid_tags_file entry the decoder has not heard reports last_seen 0."""
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(tag='FIRE', configured=True)})
        assert store.talkgroups()[0]['last_seen'] == 0
        assert store.stats()['heard'] == 0
        assert store.stats()['total'] == 1

    def test_last_seen_never_moves_backwards(self) -> None:
        """Two receivers on one system report independently, out of order."""
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=2000.0, last_freq=851_000_000)})
        store.observe('sys', {'101': tags(last_seen=1000.0, last_freq=852_000_000)})
        row = store.talkgroups()[0]
        assert row['last_seen'] == 2000.0
        assert row['last_freq'] == 851_000_000   # the frequency of the newer sighting

    def test_zero_last_seen_does_not_erase_history(self) -> None:
        """The whole point: a restart reports 0 for everything it has not heard."""
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=2000.0, last_freq=851_000_000)})
        store.observe('sys', {'101': tags(tag='FIRE', configured=True)})   # last_seen 0
        row = store.talkgroups()[0]
        assert row['last_seen'] == 2000.0
        assert row['last_freq'] == 851_000_000

    def test_count_accumulates_by_delta_not_by_value(self) -> None:
        """The decoder's counter is per-process, so only the delta may be added."""
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=1.0, count=3)})
        store.observe('sys', {'101': tags(last_seen=2.0, count=5)})
        store.observe('sys', {'101': tags(last_seen=3.0, count=5)})   # no new calls
        assert store.talkgroups()[0]['count'] == 5

    def test_count_survives_a_decoder_counter_reset(self) -> None:
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=1.0, count=10)})
        # Decoder restarts: its counter is back at 2, but 10 calls did happen.
        store.observe('sys', {'101': tags(last_seen=2.0, count=2)})
        assert store.talkgroups()[0]['count'] == 12

    def test_systems_are_separate(self) -> None:
        store = TalkgroupStore(None)
        store.observe('a', {'101': tags(last_seen=1.0)})
        store.observe('b', {'101': tags(last_seen=2.0)})
        assert len(store.talkgroups()) == 2
        assert [r['last_seen'] for r in store.talkgroups('a')] == [1.0]
        assert [r['last_seen'] for r in store.talkgroups('b')] == [2.0]

    def test_row_cap_is_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tg_metadata, 'MAX_ROWS', 2)
        store = TalkgroupStore(None)
        store.observe('sys', {str(t): tags(last_seen=1.0) for t in (1, 2, 3, 4)})
        assert store.stats()['total'] == 2

    def test_garbage_entries_are_skipped(self) -> None:
        store = TalkgroupStore(None)
        store.observe('sys', {'notanint': tags(last_seen=1.0), 'x': 'notadict',  # type: ignore[dict-item]
                              '5': tags(last_seen=1.0)})
        assert [r['tgid'] for r in store.talkgroups()] == [5]

    def test_sorted_newest_first_never_heard_last(self) -> None:
        store = TalkgroupStore(None)
        store.observe('sys', {'1': tags(last_seen=100.0),
                              '2': tags(),
                              '3': tags(last_seen=200.0)})
        assert [r['tgid'] for r in store.talkgroups()] == [3, 1, 2]


class TestMergeInto:
    def test_fills_in_a_stale_payload(self) -> None:
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=2000.0, last_freq=851_000_000, count=4)})

        live = {'101': tags(tag='FIRE', configured=True)}   # fresh decoder, never heard
        store.merge_into('sys', live)
        assert live['101']['last_seen'] == 2000.0
        assert live['101']['last_freq'] == 851_000_000
        assert live['101']['count'] == 4
        assert live['101']['tag'] == 'FIRE'          # live payload still owns the tag

    def test_live_activity_wins_over_stored(self) -> None:
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=1000.0, last_freq=851_000_000)})
        live = {'101': tags(last_seen=3000.0, last_freq=852_000_000)}
        store.merge_into('sys', live)
        assert live['101']['last_seen'] == 3000.0
        assert live['101']['last_freq'] == 852_000_000

    def test_unknown_talkgroups_are_left_alone(self) -> None:
        store = TalkgroupStore(None)
        live = {'999': tags()}
        store.merge_into('sys', live)
        assert live['999'] == tags()

    def test_does_not_invent_rows_the_decoder_has_no_config_for(self) -> None:
        """The payload describes what the decoder has; history lives in the API."""
        store = TalkgroupStore(None)
        store.observe('sys', {'101': tags(last_seen=1.0), '202': tags(last_seen=2.0)})
        live = {'101': tags()}
        store.merge_into('sys', live)
        assert set(live) == {'101'}


class TestPersistence:
    def test_round_trips_through_sqlite(self, tmp_path: Any) -> None:
        path = str(tmp_path / 'tg.sqlite')
        store = TalkgroupStore(path)
        store.observe('sys', {'101': tags(tag='FIRE', last_seen=2000.0,
                                          last_freq=851_000_000, count=7)})
        store.close()

        reopened = TalkgroupStore(path)
        row = reopened.talkgroups()[0]
        assert (row['tgid'], row['tag'], row['last_seen'], row['last_freq'], row['count']) \
            == (101, 'FIRE', 2000.0, 851_000_000, 7)
        reopened.close()

    def test_flush_is_batched_until_the_interval_elapses(self, tmp_path: Any) -> None:
        """A talkgroup seen twice a second must not be two disk writes a second."""
        path = str(tmp_path / 'tg.sqlite')
        store = TalkgroupStore(path)
        store.observe('sys', {'101': tags(last_seen=1.0)})
        assert store.flush() == 0                 # too soon
        assert store.stats()['pending_write'] == 1
        assert store.flush(force=True) == 1
        assert store.stats()['pending_write'] == 0
        store.close()

    def test_flush_writes_each_dirty_row_once(self, tmp_path: Any) -> None:
        path = str(tmp_path / 'tg.sqlite')
        store = TalkgroupStore(path)
        store.observe('sys', {str(t): tags(last_seen=float(t)) for t in range(1, 6)})
        assert store.flush(force=True) == 5
        assert store.flush(force=True) == 0       # nothing dirty any more
        store.close()

    def test_stored_last_seen_is_not_regressed_by_a_later_flush(self, tmp_path: Any) -> None:
        """Guards the SQL: the upsert takes MAX(), not the incoming value."""
        path = str(tmp_path / 'tg.sqlite')
        store = TalkgroupStore(path)
        store.observe('sys', {'101': tags(last_seen=5000.0, last_freq=851_000_000)})
        store.flush(force=True)

        with sqlite3.connect(path) as db:
            db.execute('UPDATE talkgroups SET last_seen = 9999 WHERE tgid = 101')
        # In-memory row still says 5000; force it dirty and flush.
        store.observe('sys', {'101': tags(tag='FIRE', last_seen=5000.0)})
        store.flush(force=True)
        with sqlite3.connect(path) as db:
            seen, = db.execute('SELECT last_seen FROM talkgroups WHERE tgid = 101').fetchone()
        assert seen == 9999
        store.close()

    def test_creates_missing_parent_directory(self, tmp_path: Any) -> None:
        path = str(tmp_path / 'nested' / 'deeper' / 'tg.sqlite')
        store = TalkgroupStore(path)
        store.observe('sys', {'101': tags(last_seen=1.0)})
        store.flush(force=True)
        store.close()
        assert os.path.exists(path)

    def test_an_unusable_path_degrades_to_memory_only(self, tmp_path: Any) -> None:
        """A broken database must never take the decoder down with it."""
        blocker = tmp_path / 'blocker'
        blocker.write_text('not a directory')
        store = TalkgroupStore(str(blocker / 'tg.sqlite'))
        assert store.stats()['persistent'] is False
        # Still fully functional in memory.
        store.observe('sys', {'101': tags(last_seen=1.0)})
        assert store.talkgroups()[0]['tgid'] == 101
        assert store.flush(force=True) == 0
        store.close()

    def test_a_corrupt_database_degrades_to_memory_only(self, tmp_path: Any) -> None:
        path = tmp_path / 'tg.sqlite'
        path.write_bytes(b'this is not a database' * 20)
        store = TalkgroupStore(str(path))
        assert store.stats()['persistent'] is False
        store.observe('sys', {'101': tags(last_seen=1.0)})
        assert store.talkgroups()[0]['tgid'] == 101
        store.close()


class TestTrunkUpdateWiring:
    """_note_trunk_update is what connects the decoder feed to the store."""

    @pytest.fixture(autouse=True)
    def _store(self, tmp_path: Any) -> Any:
        previous = websocket_server.talkgroup_store
        store = TalkgroupStore(None)
        websocket_server.talkgroup_store = store
        yield store
        # Held locally: one test sets the module global to None on purpose.
        store.close()
        websocket_server.talkgroup_store = previous

    def trunk_update(self, **systems: Any) -> dict[str, Any]:
        """A trunk_update shaped like tk_p25.p25_rx_ctl.to_json builds it."""
        entry: dict[str, Any] = {'json_type': 'trunk_update', 'nac': 0}
        for index, (name, tgid_tags) in enumerate(systems.items()):
            entry[str(index)] = {'type': 'p25', 'system': name, 'tgid_tags': tgid_tags}
        return entry

    def test_observes_and_merges_in_one_pass(self) -> None:
        store = websocket_server.talkgroup_store
        assert store is not None
        websocket_server._note_trunk_update(
            self.trunk_update(palmetto={'101': tags(tag='FIRE', last_seen=2000.0,
                                                    last_freq=851_000_000)}))
        assert store.talkgroups('palmetto')[0]['last_seen'] == 2000.0

        # A restart: the decoder knows the tag but has heard nothing.  The payload
        # handed to the browser must still carry the history.
        entry = self.trunk_update(palmetto={'101': tags(tag='FIRE', configured=True)})
        websocket_server._note_trunk_update(entry)
        assert entry['0']['tgid_tags']['101']['last_seen'] == 2000.0
        assert entry['0']['tgid_tags']['101']['last_freq'] == 851_000_000

    def test_multiple_systems_are_kept_apart(self) -> None:
        store = websocket_server.talkgroup_store
        assert store is not None
        websocket_server._note_trunk_update(self.trunk_update(
            alpha={'101': tags(last_seen=1000.0)},
            beta={'101': tags(last_seen=2000.0)},
        ))
        assert store.talkgroups('alpha')[0]['last_seen'] == 1000.0
        assert store.talkgroups('beta')[0]['last_seen'] == 2000.0

    def test_a_payload_with_no_tgid_tags_is_ignored(self) -> None:
        # tk_trbo emitted no tgid_tags at all before this fork added it, and the
        # scalar keys ('nac', 'json_type') must not be mistaken for systems.
        websocket_server._note_trunk_update({'json_type': 'trunk_update', 'nac': 0,
                                             '0': {'type': 'p25', 'system': 'x'}})
        assert websocket_server.talkgroup_store is not None
        assert websocket_server.talkgroup_store.stats()['total'] == 0

    def test_no_store_is_not_an_error(self) -> None:
        websocket_server.talkgroup_store = None
        websocket_server._note_trunk_update(
            self.trunk_update(x={'101': tags(last_seen=1.0)}))


class TestTalkgroupsEndpoint:
    @pytest.fixture
    def client(self, tmp_path: Any) -> Any:
        previous = websocket_server.talkgroup_store
        store = TalkgroupStore(None)
        store.observe('palmetto', {
            '101': tags(tag='FIRE DISP', last_seen=2000.0, last_freq=851_000_000, count=3),
            '202': tags(tag='EMS', configured=True),
        })
        store.observe('other', {'303': tags(tag='PD', last_seen=1000.0)})
        websocket_server.talkgroup_store = store
        with TestClient(websocket_server.app) as c:
            yield c
        store.close()
        websocket_server.talkgroup_store = previous

    def test_lists_everything_newest_first(self, client: Any) -> None:
        body = client.get('/api/talkgroups').json()
        assert body['count'] == 3
        assert [t['tgid'] for t in body['talkgroups']] == [101, 303, 202]
        assert body['talkgroups'][0]['tag'] == 'FIRE DISP'
        assert body['persistent'] is False       # memory-only in this fixture

    def test_filters_by_system(self, client: Any) -> None:
        body = client.get('/api/talkgroups?system=palmetto').json()
        assert {t['tgid'] for t in body['talkgroups']} == {101, 202}

    def test_filters_to_heard_only(self, client: Any) -> None:
        body = client.get('/api/talkgroups?heard=true').json()
        assert [t['tgid'] for t in body['talkgroups']] == [101, 303]

    def test_reports_stats_without_shadowing_the_list(self, client: Any) -> None:
        body = client.get('/api/talkgroups').json()
        assert isinstance(body['talkgroups'], list)   # not replaced by a counter
        assert body['total'] == 3 and body['heard'] == 2

    def test_is_not_cached(self, client: Any) -> None:
        assert client.get('/api/talkgroups').headers['cache-control'] == 'no-store'


class TestNoStoreConfigured:
    def test_endpoint_answers_empty_rather_than_500(self) -> None:
        previous = websocket_server.talkgroup_store
        websocket_server.talkgroup_store = None
        try:
            with TestClient(websocket_server.app) as c:
                body = c.get('/api/talkgroups').json()
            assert body == {'talkgroups': [], 'count': 0, 'persistent': False}
        finally:
            websocket_server.talkgroup_store = previous
