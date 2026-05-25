# Copyright 2017, 2018 Max H. Parke KA1RBI
# 
# This file is part of OP25
# 
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# OP25 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with OP25; see the file COPYING. If not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Boston, MA
# 02110-1301, USA.

import sys
import os
import time
import re
import json
import socket
import traceback
import threading

from gnuradio import gr
from waitress.server import create_server

import gnuradio.op25_repeater as op25_repeater

my_input_q = None
my_output_q = None
my_recv_q = None
my_port = None

# ── Optional WebSocket control server ─────────────────────────────────────────
try:
    import asyncio
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

_ws_loop = None          # asyncio event loop running in the WS thread
_ws_clients = set()      # currently connected WebSocket clients
_ws_clients_lock = threading.Lock()


async def _ws_handler(websocket, *args):
    """Handle a single WebSocket client connection."""
    with _ws_clients_lock:
        _ws_clients.add(websocket)
    try:
        async for message in websocket:
            if not isinstance(message, str):
                continue
            try:
                data = json.loads(message)
                for d in data:
                    msg = gr.message().make_from_string(
                        str(d['command']), -2, d['arg1'], d['arg2']
                    )
                    if not my_output_q.full_p():
                        my_output_q.insert_tail(msg)
            except (json.JSONDecodeError, KeyError, TypeError):
                sys.stderr.write('ws_handler: error processing message: %s\n' % message)
    except Exception:
        pass
    finally:
        with _ws_clients_lock:
            _ws_clients.discard(websocket)


def _ws_push(msg_str):
    """Push a JSON string to all connected WS clients (thread-safe, non-blocking)."""
    if not _HAS_WEBSOCKETS or _ws_loop is None:
        return
    with _ws_clients_lock:
        clients = set(_ws_clients)
    if not clients:
        return
    payload = '[' + msg_str + ']'

    async def _broadcast():
        disconnected = set()
        for client in clients:
            try:
                await client.send(payload)
            except Exception:
                disconnected.add(client)
        if disconnected:
            with _ws_clients_lock:
                _ws_clients.difference_update(disconnected)

    asyncio.run_coroutine_threadsafe(_broadcast(), _ws_loop)


def _start_ws_server(host, port):
    """Start the WebSocket control server in a daemon thread on *port*.

    The server always listens on all interfaces (host=None / 0.0.0.0) so that
    browsers connecting from remote machines can reach it, even when the HTTP
    server is bound to a specific IP address.
    """
    global _ws_loop
    # None → asyncio binds to all interfaces; avoids the HTTP server's
    # potentially restrictive binding (e.g. 127.0.0.1) being inherited here.
    ws_host = None

    async def _serve():
        try:
            async with websockets.serve(_ws_handler, ws_host, port):
                sys.stderr.write('WebSocket control server listening on 0.0.0.0:%d\n' % port)
                await asyncio.get_event_loop().create_future()  # run until cancelled
        except OSError as exc:
            sys.stderr.write('WebSocket server failed to bind on port %d: %s\n' % (port, exc))
            sys.stderr.write('  → Is port %d already in use? Is the websockets library installed?\n' % port)
        except Exception as exc:
            sys.stderr.write('WebSocket server error: %s\n' % exc)

    def _thread_main():
        global _ws_loop
        _ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ws_loop)
        try:
            _ws_loop.run_until_complete(_serve())
        except Exception as exc:
            sys.stderr.write('WebSocket server thread error: %s\n' % exc)

    t = threading.Thread(target=_thread_main, name='ws-control', daemon=True)
    t.start()

"""
fake http and ajax server module
TODO: make less fake
"""

def static_file(environ, start_response):
    content_types = { 'png': 'image/png', 'jpeg': 'image/jpeg', 'jpg': 'image/jpeg', 'gif': 'image/gif', 'css': 'text/css', 'js': 'application/javascript', 'html': 'text/html', 'ico' : 'image/x-icon'}
    img_types = 'png jpg jpeg gif'.split()
    if environ['PATH_INFO'] == '/':
        filename = 'index.html'
    else:
        filename = re.sub(r'[^a-zA-Z0-9_.\-]', '', environ['PATH_INFO'])
    suf = filename.split('.')[-1]
    pathname = '../www/www-static'
    if suf in img_types:
        pathname = '../www/images'
    pathname = '%s/%s' % (pathname, filename)
    if suf not in list(content_types.keys()) or '..' in filename or not os.access(pathname, os.R_OK):
        sys.stderr.write('404 %s\n' % pathname)
        status = '404 NOT FOUND'
        content_type = 'text/plain'
        output = status
    else:
        with open(pathname, 'rb') as f:
            output = f.read()
        content_type = content_types[suf]
        status = '200 OK'
    return status, content_type, output

def post_req(environ, start_response, postdata):
    global my_input_q, my_output_q, my_recv_q, my_port
    valid_req = False
    try:
        data = json.loads(postdata)
        for d in data:
            msg = gr.message().make_from_string(str(d['command']), -2, d['arg1'], d['arg2'])
            if not my_output_q.full_p():
                my_output_q.insert_tail(msg)
        valid_req = True
        time.sleep(0.2)
    except (json.JSONDecodeError, KeyError, TypeError):
        sys.stderr.write('post_req: error processing input: %s\n%s\n' % (postdata, traceback.format_exc()))

    resp_msg = []
    while not my_recv_q.empty_p():
        msg = my_recv_q.delete_head()
        if msg.type() == -4:
            resp_msg.append(json.loads(msg.to_string()))
    if not valid_req:
        resp_msg = []
    status = '200 OK'
    content_type = 'application/json'
    output = json.dumps(resp_msg)
    return status, content_type, output

CORS_HEADERS = [
    ('Access-Control-Allow-Origin',  '*'),
    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
    ('Access-Control-Allow-Headers', 'Content-Type'),
]

def http_request(environ, start_response):
    if environ['REQUEST_METHOD'] == 'OPTIONS':
        # CORS preflight
        response_headers = [('Content-Length', '0')] + CORS_HEADERS
        start_response('204 No Content', response_headers)
        return [b'']
    elif environ['REQUEST_METHOD'] == 'GET':
        status, content_type, output = static_file(environ, start_response)
    elif environ['REQUEST_METHOD'] == 'POST':
        postdata = environ['wsgi.input'].read()
        status, content_type, output = post_req(environ, start_response, postdata)
    else:
        status = '200 OK'
        content_type = 'text/plain'
        output = status
        sys.stderr.write('http_request: unexpected input %s\n' % environ['PATH_INFO'])

    response_headers = [('Content-type', content_type),
                        ('Content-Length', str(len(output)))] + CORS_HEADERS
    start_response(status, response_headers)

    if sys.version[0] > '2':
        if type(output) is str:
            output = output.encode()

    return [output]

def application(environ, start_response):
    failed = False
    try:
        result = http_request(environ, start_response)
    except Exception:
        failed = True
        sys.stderr.write('application: request failed:\n%s\n' % traceback.format_exc())
        sys.exit(1)
    return result

def process_qmsg(msg):
    if my_recv_q.full_p():
        my_recv_q.delete_head_nowait()   # ignores result
    if my_recv_q.full_p():
        return
    if not my_recv_q.full_p():
        my_recv_q.insert_tail(msg)
    # Push to any connected WebSocket clients immediately
    if msg.type() == -4:
        try:
            _ws_push(msg.to_string())
        except Exception:
            pass

class http_server(object):
    def __init__(self, input_q, output_q, endpoint, **kwds):
        global my_input_q, my_output_q, my_recv_q, my_port
        host, port = endpoint.split(':')
        if my_port is not None:
            raise AssertionError('this server is already active on port %s' % my_port)
        my_input_q = input_q
        my_output_q = output_q
        my_port = int(port)

        my_recv_q = gr.msg_queue(10)
        self.q_watcher = queue_watcher(my_input_q, process_qmsg)

        try:
            self.server = create_server(application, host=host, port=my_port, threads=6)
        except (OSError, ValueError):
            sys.stderr.write('Failed to create http terminal server\n%s\n' % traceback.format_exc())
            sys.exit(1)

        # Start WebSocket control server on port+1 if websockets library is available
        if _HAS_WEBSOCKETS:
            try:
                _start_ws_server(host, my_port + 1)
            except Exception:
                sys.stderr.write('Failed to start WebSocket server\n%s\n' % traceback.format_exc())

    def run(self):
        self.server.run()

class queue_watcher(threading.Thread):
    def __init__(self, msgq,  callback, **kwds):
        threading.Thread.__init__ (self, **kwds)
        self.setDaemon(1)
        self.msgq = msgq
        self.callback = callback
        self.keep_running = True
        self.start()

    def run(self):
        while(self.keep_running):
            if not self.msgq.empty_p(): # check queue before trying to read a message to avoid deadlock at startup
                msg = self.msgq.delete_head()
                if msg is not None:
                    self.callback(msg)
                else:
                    self.keep_running = False
            else: # empty queue
                time.sleep(0.01)
