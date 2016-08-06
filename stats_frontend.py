from flask import Flask, request
import redis
import json
import traceback
import logging
logging.basicConfig( level = logging.DEBUG )

app = Flask(__name__, static_url_path='/static')

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 5

teams = {0: 0, 1:1, 2:2, 3:3, "FREE": 0, "RED": 1, "BLUE": 2, "SPECTATOR": 3}

def teamMap(nameStr):
    return 

def getIncompleteMatchInfo(guid):
    raw_events = r.lrange("events_%s" % guid, 0, -1)
    events = map(json.loads, raw_events)
    last_time = events[-1]['TIME']
    response = {}
    response['LAST_EVENT_TIME'] = last_time
    teamed_players = [ set(), set(), set(), set() ]

    for e in events:
        if 'NAME' in e and 'TEAM' in e:
            teamed_players[teams[e['TEAM']]].add(e['NAME'])

        if 'KILLER' in e and e['KILLER'] is not None:
            teamNum = teams[e['KILLER']['TEAM']]
            teamed_players[teamNum].add(e['KILLER']['NAME'])

        if 'VICTIM' in e and e['VICTIM'] is not None:
            teamed_players[teams[e['VICTIM']['TEAM']]].add(e['VICTIM']['NAME'])
    response['TEAMS'] = map(list, teamed_players)
    response['MATCH_GUID'] = guid
    return response

@app.route("/update")
def update():
    last_match = request.args.get('lastMatch', '')
    recent_matches = r.lrange('recent_matches', 0, -1)
    if last_match is not None:
        i = 0
        for match in recent_matches:
            if match == last_match:
                break
            i = i+1
    recent_matches = recent_matches[0:i]

    ongoing_match_ids = r.smembers('ongoing_matches')
    ongoing_matches = map(getIncompleteMatchInfo, ongoing_match_ids)

    response = {'matches': [], 'ongoing': ongoing_matches}
    for match_guid in recent_matches:
        try:
            match_report = json.loads( r.get('report_%s' % match_guid) )
            match_report['STATS'] = []
            match_report['EVENTS'] = []
            if not match_report:
                continue
            try:
                player_stats = r.lrange('stats_%s' % match_guid, 0, -1)
                for player in player_stats:
                    match_report['STATS'].append( json.loads(player) )
            except:
                logging.info( traceback.format_exc() )
                pass
#            try:
#                match_events = r.lrange('events_%s' % match_guid, 0, -1)
#                for event in match_events:
#                    match_report['STATS'].append( json.loads(event) )
#            except:
#                logging.info( traceback.format_exc() )
#                pass
            response['matches'].append(match_report)
        except Exception, e:
            logging.info( traceback.format_exc() )
            continue
    return json.dumps(response)

@app.route("/")
def index():
    return app.send_static_file('index.html')

if __name__ == "__main__":
    r = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    app.run(debug=True, host='0.0.0.0', port=8080)
