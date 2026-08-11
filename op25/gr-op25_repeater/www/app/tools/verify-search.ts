// Drives the SHIPPED call-search and highlight modules, not a copy, and asserts
// the semantics the UI's copy claims: every term must match, terms may land in
// different fields, a talkgroup-only call is still findable with transcription
// off, and nothing the user can type into the box can throw.
//
// Bundled with esbuild and run in Node, like tools/verify-agc.ts.
import { matchesClip, searchTerms } from '../src/utils/callSearch';
import { highlight } from '../src/utils/callTranscripts';

let failures = 0;

function check(name: string, ok: boolean, detail = '') {
  if (ok) {
    console.log(`  ok   ${name}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

const FIRE = {
  talkgroup: 'W Cola Fire Disp',
  tgid: 4501,
  transcript: 'Engine 12 responding to a structure fire on Sunset',
};
const NO_TRANSCRIPT = { talkgroup: 'RCHP Dispatch', tgid: 1101 };
const UNTAGGED = { tgid: 7777, transcript: 'copy that, 10-33 traffic' };
const DISCARDED = {
  talkgroup: 'EMS 3',
  tgid: 2003,
  discarded_transcript: 'Thank you for watching',
};

const q = (s: string) => searchTerms(s);

console.log('call search');

// --- the two fields the feature exists for -------------------------------
check('finds a word from the transcript', matchesClip(FIRE, q('structure')));
check('finds a word from the talkgroup name', matchesClip(FIRE, q('cola')));
check('case-insensitive both ways', matchesClip(FIRE, q('SUNSET')) && matchesClip(FIRE, q('w cola')));
check('a call with no transcript is still findable by talkgroup',
  matchesClip(NO_TRANSCRIPT, q('rchp')));
check('a call with no talkgroup name is findable by TGID',
  matchesClip(UNTAGGED, q('7777')));
check('TGID is matched as bare text, not the rendered "TG 7777" label',
  matchesClip(UNTAGGED, q('777')) && !matchesClip(UNTAGGED, q('tg 7777')));

// --- multi-term AND, spanning fields ------------------------------------
check('every term must match', !matchesClip(FIRE, q('structure ambulance')));
check('terms may land in different fields', matchesClip(FIRE, q('cola fire')));
check('terms may land in different fields (transcript + tgid)',
  matchesClip(FIRE, q('4501 sunset')));
check('extra whitespace is not a term', matchesClip(FIRE, q('   cola   fire  ')));
check('an empty query matches everything',
  matchesClip(FIRE, q('')) && matchesClip(NO_TRANSCRIPT, q('  ')));

// --- fields must be tested separately, never concatenated ----------------
// "displ" spans the end of the talkgroup and the start of the transcript only
// if the two are joined; it exists in neither.
check('a term cannot straddle two fields',
  !matchesClip({ talkgroup: 'AB', tgid: 1, transcript: 'CD' }, q('bc')));

// --- what is displayed is what is searched ------------------------------
check('a discarded (hallucinated) transcript is searchable, because it is shown',
  matchesClip(DISCARDED, q('watching')));
check('a clip with no searchable text at all matches nothing',
  !matchesClip({ tgid: 0 }, q('anything')));

// --- nothing typed into the box may throw -------------------------------
for (const raw of ['(', '10-33', '*', 'a**b', '[unclosed', '\\', '?', '$^', 'c++']) {
  let ok = true;
  try {
    matchesClip(FIRE, q(raw));
    highlight(FIRE.transcript, [], q(raw));
  } catch (e) {
    ok = false;
    check(`query ${JSON.stringify(raw)} does not throw`, false, String(e));
  }
  if (ok) check(`query ${JSON.stringify(raw)} does not throw`, true);
}

console.log('highlight');

// --- marking, and the keyword/search distinction -------------------------
const parts = highlight('structure fire on Sunset', ['fire'], q('sunset structure'));
const hits = parts.filter((p) => typeof p !== 'string') as { hit: string; kind: string }[];
check('marks both keyword and search terms',
  hits.length === 3, JSON.stringify(hits));
check('a keyword is marked as a keyword',
  hits.some((h) => h.hit === 'fire' && h.kind === 'keyword'), JSON.stringify(hits));
check('a search term is marked as a search hit',
  hits.some((h) => h.hit === 'Sunset' && h.kind === 'search'), JSON.stringify(hits));
check('the original casing survives the round trip',
  parts.map((p) => (typeof p === 'string' ? p : p.hit)).join('') === 'structure fire on Sunset');

const both = highlight('a fire here', ['fire'], q('fire'))
  .filter((p) => typeof p !== 'string') as { kind: string }[];
check('a run that is both is reported as a keyword',
  both.length === 1 && both[0].kind === 'keyword', JSON.stringify(both));

check('no terms leaves the text untouched',
  highlight('nothing to mark', [], []).join('') === 'nothing to mark');

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
