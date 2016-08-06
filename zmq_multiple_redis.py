#!/usr/bin/env python

import sys
import time
import json
import struct
import argparse
import pprint
import redis
import logging
import traceback
logging.basicConfig( level = logging.DEBUG )

# see https://github.com/zeromq/pyzmq/wiki/Building-and-Installing-PyZMQ
# QuakeLive requires CZMQ 3.x APIs or newer (libzmq 4.x)
import zmq

import unittest

class ZMQInfo:
    def __init__(self, socket, monitor):
        self.socket = socket
        self.monitor = monitor

POLL_TIMEOUT = 50
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 5

hosts = [
    'tcp://172.17.2.10:26900',
    'tcp://172.17.2.10:26901',
    'tcp://172.17.2.10:26902',
    'tcp://172.17.2.10:26903',
    'tcp://172.17.2.10:26904',
    'tcp://172.17.2.10:26905',
    'tcp://172.17.2.10:27015',
    'tcp://172.17.2.10:27016',
    'tcp://172.17.2.10:27017',
    'tcp://172.17.2.10:27018',
    'tcp://172.17.2.10:27019',
    'tcp://172.17.2.10:27020',
    'tcp://172.17.2.11:26900',
    'tcp://172.17.2.11:26901',
    'tcp://172.17.2.11:26902',
    'tcp://172.17.2.11:26903',
]

connections = []


def _readSocketEvent( msg ):
    # NOTE: little endian - hopefully that's not platform specific?
    event_id = struct.unpack( '<H', msg[:2] )[0]
    # NOTE: is it possible I would get a bitfield?
    event_names = {
        zmq.EVENT_ACCEPTED : 'EVENT_ACCEPTED',
        zmq.EVENT_ACCEPT_FAILED : 'EVENT_ACCEPT_FAILED',
        zmq.EVENT_BIND_FAILED : 'EVENT_BIND_FAILED',
        zmq.EVENT_CLOSED : 'EVENT_CLOSED',
        zmq.EVENT_CLOSE_FAILED : 'EVENT_CLOSE_FAILED',
        zmq.EVENT_CONNECTED : 'EVENT_CONNECTED',
        zmq.EVENT_CONNECT_DELAYED : 'EVENT_CONNECT_DELAYED',
        zmq.EVENT_CONNECT_RETRIED : 'EVENT_CONNECT_RETRIED',
        zmq.EVENT_DISCONNECTED : 'EVENT_DISCONNECTED',
        zmq.EVENT_LISTENING : 'EVENT_LISTENING',
        zmq.EVENT_MONITOR_STOPPED : 'EVENT_MONITOR_STOPPED',
    }
    event_name = event_names[ event_id ] if event_names.has_key( event_id ) else '%d' % event_id
    event_value = struct.unpack( '<I', msg[2:] )[0]
    return ( event_id, event_name, event_value )

def _checkMonitor( monitor ):
    try:
        event_monitor = monitor.recv( zmq.NOBLOCK )
    except zmq.Again:
        #logging.debug( 'again' )
        return

    ( event_id, event_name, event_value ) = _readSocketEvent( event_monitor )
    event_monitor_endpoint = monitor.recv( zmq.NOBLOCK )
    logging.info( 'monitor: %s %d endpoint %s' % ( event_name, event_value, event_monitor_endpoint ) )    

def verbose( args ):
    try:
        context = zmq.Context()

        r = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        for host in hosts:
            print host
            socket = context.socket( zmq.SUB )
            monitor = socket.get_monitor_socket( zmq.EVENT_ALL )
            if ( args.password is not None ):
                logging.info( 'setting password for access' )
                try:
                    # NOTE: doesn't want unicode (Windows pyzmq 14.5.0)
                    socket.PLAIN_USERNAME = 'stats'
                    socket.PLAIN_PASSWORD = args.password
                    socket.ZAP_DOMAIN = 'stats'
                except Exception as e:
                    logging.info( 'zmq syntax sugar broken? trying setsockopt_string' )
                    logging.info( traceback.format_exc() )
                    from zmq.sugar import constants
                    for c in ( 'PLAIN_USERNAME', 'PLAIN_PASSWORD', 'ZAP_DOMAIN', ):
                        logging.info( '%s: %s' % ( c, repr( constants.__dict__[c] ) ) )
                    # NOTE: requires unicode strings
                    socket.setsockopt_string( 45, u'stats' )
                    socket.setsockopt_string( 46, args.password.decode('unicode-escape') )
                    socket.setsockopt_string( 55, u'stats' )
            socket.connect( host )
            socket.setsockopt( zmq.SUBSCRIBE, '' )
            print( 'Connected SUB to %s' % host )
            connections.append( ZMQInfo(socket, monitor) )
        while ( True ):
            for connection in connections:
                event = connection.socket.poll( POLL_TIMEOUT )
                # check if there are any events to report on the socket
                _checkMonitor( connection.monitor )

                if ( event == 0 ):
                    #logging.info( 'poll loop' )
                    continue
                
                try:
                    msg = connection.socket.recv_json( zmq.NOBLOCK )
                except zmq.error.Again:
                    break
                except Exception, e:
                    logging.info( e )
                    break
                else:
                    try:
                        guid = msg['DATA']['MATCH_GUID']
                        data = msg['DATA']
                        json_msg = json.dumps(msg['DATA'])
                        table = msg['TABLE'] if 'TABLE' in msg else msg['TYPE']
                        if table in [ 'PLAYER_DEATH', 'PLAYER_MEDAL', 'PLAYER_SWITCHTEAM', 'PLAYER_CONNECT', 'PLAYER_DISCONNECT']: 
                            r.rpush('events_%s' % guid, json_msg)
                            logging.info("Pushing %s event to events_%s" % (table, guid,))
                        elif table in [ 'PLAYER_STATS' ]:
                            r.rpush('stats_%s' % guid, json_msg)
                            logging.info("Pushing stats to stats_%s" % guid)
                        elif table in [ 'MATCH_REPORT' ]:
                            r.set('report_%s' % guid, json_msg)                  
                            r.lpush('recent_matches', guid)
                            logging.info("Pushing match to report_%s" % guid)
                        elif table not in ['PLAYER_KILL']:
                            logging.info( pprint.pformat( msg ) )

                        if table == 'MATCH_REPORT':
                            r.srem('ongoing_matches', guid)
                        elif table == 'MATCH_STARTED':
                            r.sadd('ongoing_matches', guid)
                    except Exception, e:
                        logging.info( msg )
                        logging.info( traceback.format_exc() )
                        continue
    except Exception, e:
        logging.info( e )
    finally:
        raw_input( 'Press Enter to continue...' )

if ( __name__ == '__main__' ):
    logging.info( 'zmq python bindings %s, libzmq version %s' % ( repr( zmq.__version__ ), zmq.zmq_version() ) )
    parser = argparse.ArgumentParser( description = 'Verbose QuakeLive server statistics' )
    parser.add_argument( '--password', required = False )
    args = parser.parse_args()
    #logging.debug( repr( args ) )
    verbose( args )
