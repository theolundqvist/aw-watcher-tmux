"""
Script that computes how many hours was spent in a git repo today.

Also saves the matching work-events to a JSON file (for auditing purposes).

modified from https://github.com/ActivityWatch/aw-client/blob/master/examples/working_hours.py
"""

import argparse 
import json
import re
from copy import deepcopy
import sys, os
from datetime import datetime, timedelta, time
from typing import List, Tuple, Dict

from tabulate import tabulate

import aw_client
from aw_client import queries
from aw_core import Event
from aw_transform import flood


OUTPUT_HTML = os.environ.get("OUTPUT_HTML", "").lower() == "true"


def _pretty_timedelta(td: timedelta) -> str:
    s = str(td)
    s = re.sub(r"^(0+[:]?)+", "", s)
    # s = s.rjust(len(str(td)), " ")
    s = re.sub(r"[.]\d+", "", s)
    return s


assert _pretty_timedelta(timedelta(seconds=120)) == "2:00"
assert _pretty_timedelta(timedelta(hours=9, minutes=5)) == "9:05:00"


def generous_approx(events: List[dict], max_break: float) -> timedelta:
    """
    Returns a generous approximation of worked time by including non-categorized time when shorter than a specific duration

    max_break: Max time (in seconds) to flood when there's an empty slot between events
    """
    events_e: List[Event] = [Event(**e) for e in events]
    return sum(
        # map(lambda e: e.duration, flood(events_e, max_break)),
        map(lambda e: e.duration, flood(events_e, max_break)),
        timedelta(),
    )


def cut_and_remove_overlapping(events: List[dict], event: dict) -> List[dict]:
    """
    Makes perfect room for event in events by cutting events that overlap with the event. If an event in events is bigger than event, it is split into two events.
    """
    e = event
    start = datetime.fromisoformat(e['timestamp'])
    end = start + timedelta(seconds=e['duration'])

    for j in range(len(events)):
        other = events[j]
        if other['duration'] == 0: continue
        other_start = datetime.fromisoformat(other['timestamp'])
        other_end = other_start + timedelta(seconds=other['duration'])

        if(start >= other_end or end <= other_start): 
            """ if the event and events event does not overlap """
            continue
        if start <= other_start and end >= other_end:
            """ event event is bigger than events event """
            other['duration'] = 0
            continue
        if start > other_start:
            """ event event starts after events event, split events event """
            other0 = deepcopy(other)
            other0['duration'] = (start-other_start).total_seconds()
            other['duration'] = other['duration'] - other0['duration']
            other['timestamp'] = start.isoformat()
            if end >= other_end:
                # smaller event is noother overlapped by event event
                other['duration'] = 0
            events.insert(j, other0)
        if end < other_end:
            """ event event ends before events event, split events event """
            other1 = deepcopy(other)
            other1['duration'] = (other_end-end).total_seconds()
            other['duration'] = 0# other['duration'] - other1['duration']
            other1['timestamp'] = end.isoformat()
            events.insert(j+1, other1)

    return [e for e in events if e['duration'] > 0.05]


def print_negative_gap(e1, e2, prefix="\nFound negative gap: "):
    firstEnd = datetime.fromisoformat(e1['timestamp'])+timedelta(seconds=e1['duration']) 
    secondIso = datetime.fromisoformat(e2['timestamp'])
    overlap = (firstEnd-secondIso)
    def name(e):
        return e['data'].get('app') or e['data'].get('title') or e['data'].get("status")
    print(prefix, e1['data']['type'], "(",e1['duration'],"s, ", name(e1),") and ", e2['data']['type'], "(",e2['duration']," s, ",name(e2),") of ", overlap.total_seconds(), " seconds. ", "end: ", firstEnd.time(), " start: ", secondIso.time())

def remove_negative_gap(events: List[dict]) -> List[dict]:
    events = sort_events(events)
    events = [e for e in events if e['duration'] > 0.05]
    wrong = 0
    for i in range(len(events)-2):
        first = events[i]
        second = events[i+1]
        firstIso = datetime.fromisoformat(first['timestamp'])
        secondIso = datetime.fromisoformat(second['timestamp'])
        firstEnd = firstIso+timedelta(seconds=first['duration'])
        if firstEnd > secondIso:
            wrong += 1
            overlap = (firstEnd-secondIso)
            print_negative_gap(first, second)
            # """ prioritize tmux data """
            if(first['data']['type'] == 'window'):
                # """ if the first event is window, we shorten it """
                first['duration'] = first['duration'] - overlap.total_seconds()
            else:
                # """ if the first event is tmux, we move the other forward and shorten it """
                second['timestamp'] = (secondIso+overlap).isoformat()
                second['duration'] = second['duration'] - overlap.total_seconds()
            # """ Move negative duration events away for deletion """
            if(second['duration'] < 0.05):
                second['duration'] = 0
                second['timestamp'] = (firstEnd-timedelta(days=2)).isoformat()
            print_negative_gap(first, second, prefix="Fixed negative gap: ")

    if wrong > 0:
        print("Found ", wrong, " negative gaps out of ", len(events), " events")
    events = [e for e in events if e['duration'] > 0.05]
    return events

def sort_events(events: List[dict]) -> List[dict]:
    return sorted(events, key=lambda e: datetime.fromisoformat(e['timestamp']))

def subtract_times(events: List[dict], subtract: List[dict]) -> List[dict]:
    """ remove all space that is covered by cut from events """
    for c in subtract:
        events = cut_and_remove_overlapping(events, c)
    return events

def filter_work(afk: List[dict], window:List[dict], editor: List[dict], repo_url)-> List[dict]:
    afk = sort_events(afk) 
    window = sort_events(window) 
    editor = sort_events(editor) 

    afk = remove_negative_gap(afk)
    editor = remove_negative_gap(editor)
    window = remove_negative_gap(window)
    loginwindow = [e for e in window if e['data']['app'] == 'loginwindow']
    window = [e for e in window if e['data']['app'] != 'loginwindow']

    

    """ remove all editor time from window """
    window = subtract_times(events=window, subtract=editor);

    """ merge window and editor """
    work = window + editor

    """ remove all afk time from work """
    work = subtract_times(events=work, subtract=afk);

    """ remove all loginwindow time from work """
    work = subtract_times(events=work, subtract=loginwindow);

    """ remove all time from work that is too short """
    work = [e for e in work if e['duration'] > 0.05]
    """ TODO: filter based upon repo_url """

    """ double check no negative gaps """
    work = remove_negative_gap(work)
    return work

def get_timeperiods(nbr_days):
    td1d = timedelta(days=nbr_days)
    day_offset = timedelta(hours=4)

    now = datetime.now().astimezone()
    today = (datetime.combine(now.date(), time()) + day_offset).astimezone()

    # timeperiods = [(today - i * td1d, today - (i - 1) * td1d) for i in range(5)][]
    timeperiods = [(today, today+td1d)]
    timeperiods.reverse()
    return timeperiods

def report(events, result, start, repo_url):
    res = "date: "+start.date().isoformat()+"\n"
    # for break_time in [0, 1 * 60, 2 * 60, 5 * 60, 10 * 60]:
    repo_name = "all"
    if repo_url is not None: repo_name = re.sub(r".*\/(.*)\/(.*)", r"\1_\2", repo_url)
    res += f"{repo_url}\n"
    res += f"{repo_name}\n"
    res += f"{start.date()}\n"
    res += f"{_pretty_timedelta(result)}"
    return res

def save(events, results, timeperiods, repo_url=None, path=None):
    # fn = f"~/Documents/hour_logs/hours_{start.date()}_{end.date()}.json"
    for i, (start, end) in enumerate(timeperiods):
        for e in events[i]:
            del e['data']['type']
        repo_name = "all"
        if repo_url is not None: repo_name = re.sub(r".*\/(.*)\/(.*)", r"\1_\2", repo_url)

        fn = f"~/Documents/hours/{start.date().year}/{start.date().month}/{start.date().day}/{repo_name}"
        if path is not None: fn = path
        fn = os.path.expanduser(fn)
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with open(fn+".json", "w") as f:
            print(f"Saving events to {fn}.json")
            name = "tmux-worked-hours-test"
            buckets = {"buckets": {name: {
                "id": name, 
                "created": datetime.now().astimezone() .isoformat(),
                "type": f"com.{name}.test", 
                "client":name,
                "hostname":"testhost",
                "events": events[i],
            }}}
            json.dump(buckets, f, indent=2)
        with open(fn+"-report.txt", "w") as f:
            print(f"Saving result to {fn}.txt")
            f.write(report(events, results, start, repo_url))

def query(timeperiods):
    aw = aw_client.ActivityWatchClient()
    afk_events = aw.query('RETURN = query_bucket(find_bucket("aw-watcher-afk_"));', timeperiods)
    window_events = aw.query('RETURN = query_bucket(find_bucket("aw-watcher-window_"));', timeperiods)
    editor_events = aw.query('RETURN = query_bucket(find_bucket("aw-watcher-tmux-editor"));', timeperiods)
    for i, t in enumerate(timeperiods):
        afk_events[i] = [e for e in afk_events[i] if e['data']['status']=="afk"]
        for e in afk_events[i]:
            e['data']['type'] = 'afk'
        for e in window_events[i]:
            e['data']['type'] = 'window'
        for e in editor_events[i]:
            e['data']['type'] = 'editor'

    return [(afk_events[i], window_events[i], editor_events[i]) for i in range(len(timeperiods))]

def calc_time(timeperiods, repo_url):
    events = query(timeperiods)
    worked = [] 

    for i, (start, stop) in enumerate(timeperiods):
        (afk, window, editor) = events[i]
        worked.append(filter_work(afk, window, editor, repo_url))
    # print(worked)

    """ calculate total time worked in each time period """
    ok_idle_time = 60 * 5
    results = [generous_approx(w, ok_idle_time) for w in worked]
    total = _pretty_timedelta(sum(results, timedelta()))
    if args.save: save(worked, results, timeperiods, repo_url=args.repo, path=args.path or None)
    if args.report: 
        for i, (start, stop) in enumerate(timeperiods):
            print(report(worked[i], results[i], start, repo_url))
    return (results, total)






if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",'-g', help="Filter on certain git repo (url or fullname)", type=str)
    parser.add_argument("--save", '-s', help="Save detailed results to file", action='store_true')
    parser.add_argument("--report", '-r', help="Report detailed results to the terminal", action='store_true')
    parser.add_argument("--path", '-p', help="Save to this path", type=str)
    parser.add_argument("--verbose", '-v', help="Print more info", action='store_true')
    args=parser.parse_args()

    if args.repo is None: 
        print("Using all repos")
    elif 'https' not in args.repo:
        args.repo = 'https://github.com/'+args.repo
        print("Using repo:", args.repo)

    timeperiods = get_timeperiods(1)
    (results, total) = calc_time(timeperiods, args.repo)


    print("total:", total)

