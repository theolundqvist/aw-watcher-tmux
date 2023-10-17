"""
Script that computes how many hours was spent in a regex-specified "work" category for each day in a given month.

Also saves the matching work-events to a JSON file (for auditing purposes).

https://github.com/ActivityWatch/aw-client/blob/master/examples/working_hours.py
"""

import json
import re
import sys, os
from datetime import datetime, timedelta, time
from typing import List, Tuple, Dict

from tabulate import tabulate

import aw_client
from aw_client import queries
from aw_core import Event
from aw_transform import flood


EXAMPLE_REGEX = r"Arc|Alacritty"
OUTPUT_HTML = os.environ.get("OUTPUT_HTML", "").lower() == "true"


def _pretty_timedelta(td: timedelta) -> str:
    s = str(td)
    s = re.sub(r"^(0+[:]?)+", "", s)
    s = s.rjust(len(str(td)), " ")
    s = re.sub(r"[.]\d+", "", s)
    return s


assert _pretty_timedelta(timedelta(seconds=120)) == "   2:00"
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

def remove_negative_gap(events: List[dict]) -> List[dict]:
    events = sorted(events, key=lambda e: datetime.fromisoformat(e['timestamp']))
    wrong = 0
    for i in range(len(events)-2):
        firstIso = datetime.fromisoformat(events[i]['timestamp'])
        secondIso = datetime.fromisoformat(events[i+1]['timestamp'])
        firstEnd = firstIso+timedelta(seconds=events[i]['duration'])
        if firstEnd > secondIso:
            wrong += 1
            events[i]['duration'] = events[i]['duration'] - (firstEnd-secondIso).total_seconds()
    print("Found ", wrong, " negative gaps out of ", len(events), " events")
    return events




def query(regex: str = EXAMPLE_REGEX, save=False):
    td1d = timedelta(days=1)
    day_offset = timedelta(hours=4)

    now = datetime.now().astimezone()
    today = (datetime.combine(now.date(), time()) + day_offset).astimezone()

    #timeperiods = [(today - i * td1d, today - (i - 1) * td1d) for i in range(5)]
    timeperiods = [(today, today+td1d)]
    timeperiods.reverse()

    # categories: List[Tuple[List[str], Dict]] = [
    #     (
    #         ["Work"],
    #         {
    #             "type": "regex",
    #             "regex": regex,
    #             "ignore_case": True,
    #         },
    #     )
    # ]
    #
    aw = aw_client.ActivityWatchClient()
    #
    # canonicalQuery = queries.canonicalEvents(
    #     queries.DesktopQueryParams(
    #         bid_window="aw-watcher-window_",
    #         bid_afk="aw-watcher-afk_",
    #         classes=categories,
    #         filter_classes=[["Work"]],
    #     )
    # )
    # query = f"""
    # {canonicalQuery}
    # duration = sum_durations(events);
    # RETURN = {{"events": events, "duration": duration}};
    # """
    query = f"""
    tmux = flood(query_bucket(find_bucket("aw-watcher-tmux-editor")));
    window = flood(query_bucket(find_bucket("aw-watcher-window_")));

    not_afk = flood(query_bucket(find_bucket("aw-watcher-afk_")));
    not_afk = filter_keyvals(not_afk, "status", ["not-afk"]);

    events = concat(window, tmux);
    events = filter_period_intersect(events, not_afk);
    loggedin = exclude_keyvals(events, "app", ["loginwindow"]);
    duration = sum_durations(loggedin);
    RETURN = {{"events": loggedin, "duration": duration}};
    """
    # merged_events = merge_events_by_keys(tmux_events, ["git_url", "title"]);
    # merged_events = filter_keyvals(merged_events, "title", ["dotfiles"]);



    res = aw.query(query, timeperiods)
    for i, (start, stop) in enumerate(timeperiods):
        res[i]['events'] = remove_negative_gap(res[i]['events'])

    for i, (start, stop) in enumerate(timeperiods):
        res[i]['events'] = remove_negative_gap(res[i]['events'])


    print("Period: ", timeperiods[0][0], timeperiods[0][1])
    for break_time in [0, 1 * 60, 2 * 60, 5 * 60, 10 * 60]:
        _print(
            # timeperiods, res, break_time, {"category_rule": categories[0][1]["regex"]}
            timeperiods, res, break_time, {}
        )

    if save:
        for i, (start, end) in enumerate(timeperiods):
            # fn = f"~/Documents/hour_logs/hours_{start.date()}_{end.date()}.json"
            fn = "hours.json"
            with open(fn, "w") as f:
                # print(f"Saving to {fn}...")
                name = "tmux-worked-hours-test"
                events = res[i]['events']
                buckets = {"buckets": {name: {
                    "id": name, 
                    "created": now.isoformat(),
                    "type": f"com.{name}.test", 
                    "client":name,
                    "hostname":"testhost",
                    "events": events,
                }}}
                json.dump(buckets, f, indent=2)
    return _pretty_timedelta(generous_approx(res[0]["events"], 300))


def _print(timeperiods, res, break_time, params: dict):
    # print("Using:")
    print(f"break_time: {break_time/60} min")
    # print("\n".join(f"  {key}={val}" for key, val in params.items()))
    # tab = tabulate(
    #         [
    #             [
    #                 start.date(),
    #                 # Without flooding:
    #                 # _pretty_timedelta(timedelta(seconds=res[i]["duration"])),
    #                 # With flooding:
    #                 _pretty_timedelta(generous_approx(res[i]["events"], break_time)),
    #                 len(res[i]["events"]),
    #             ]
    #             for i, (start, stop) in enumerate(timeperiods)
    #         ],
    #         headers=["Date", "Duration", "Events"],
    #         colalign=(
    #             "left",
    #             "right",
    #         ),
    #         tablefmt="html" if OUTPUT_HTML else "simple",
    #     )
    # print(tab)
    # print(
    #     f"Total: {sum((generous_approx(res[i]['events'], break_time) for i in range(len(timeperiods))), timedelta())}"
    # )
    # print("")
    print(_pretty_timedelta(generous_approx(res[0]["events"], break_time)))


if __name__ == "__main__":

    res = query(save=True)
    print("res:", res)

