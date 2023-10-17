#!/opt/homebrew/bin/bash

get_tmux_option() {
  local option_value=$(tmux show-option -gqv "$1");
  echo ${option_value:-$2}
}

######
# Configurable options
#
# Usage examle:
# set -g @aw-watcher-tmux-host 'my.aw-server.test'
POLL_INTERVAL=$(get_tmux_option "@aw-watcher-tmux-poll-interval" 10) # seconds
HOST=$(get_tmux_option "@aw-watcher-tmux-host" "localhost")
PORT=$(get_tmux_option "@aw-watcher-tmux-port" "5600")
PULSETIME=$(get_tmux_option "@aw-watcher-tmux-pulsetime" "120.0")

BUCKET_ID="aw-watcher-tmux-editor"
API_URL="http://$HOST:$PORT/api"

######
# Related documentation:
#  * https://github.com/tmux/tmux/wiki/Formats
#  * https://github.com/tmux/tmux/wiki/Advanced-Use#user-content-getting-information
#


### FUNCTIONS

DEBUG=0
TMP_FILE=$(mktemp)
echo $TMP_FILE

init_bucket() {
    HTTP_CODE=$(curl -X GET "${API_URL}/0/buckets/$BUCKET_ID" -H "accept: application/json" -s -o /dev/null -w %{http_code})
    if (( $HTTP_CODE == 404 )) # not found
    then
        # JSON="{\"client\":\"$BUCKET_ID\",\"type\":\"tmux.sessions\",\"hostname\":\"$(hostname)\"}"
        JSON="{\"name\":\"${BUCKET_ID}\",\"type\":\"app.editor.activity\",\"client\":\"aw-watcher-tmux-editor\",\"hostname\":\"$(hostname)\"}"
        HTTP_CODE=$(curl -X POST "${API_URL}/0/buckets/$BUCKET_ID" -H "accept: application/json" -H "Content-Type: application/json" -d "$JSON"  -s -o /dev/null -w %{http_code})
        if (( $HTTP_CODE != 200 ))
        then
            echo "ERROR creating bucket"
            echo $JSON
            echo $HTTP_CODE
            
            exit -1
        fi
    fi
}

log_to_bucket() {
    sess=$1
    current_path=$(tmux display -t $sess -p '#{pane_current_path}')
    repo_url=$(cd $current_path && git config --get remote.origin.url | sed -r 's/.*(\@|\/\/)(.*)(\:|\/)([^:\/]*)\/([^\/\.]*)(\.git){0,1}/https:\/\/\2\/\4\/\5/')
    git_branch=$(cd $current_path && git branch --show-current)
    git_full_name=$(printf $repo_url | sed -r 's/.*\/(.*)\/(.*)/\1\/\2/')
    title=$(echo $repo_url | sed -r 's/.*\/(.*)/\1/')
    [ -z "$title" ] && title=$(tmux display -t $sess -p '#{session_name}')

    ## TODO: dont update if repo is the same, or something
    DATA=$(tmux display -t $sess -p "{\"title\":\"${title}\",\"repo_url\":\"${repo_url}\", \"session_name\":\"#{session_name}\",\"window_name\":\"#{window_name}\",\"pane_title\":\"#{pane_title}\",\"pane_current_command\":\"#{pane_current_command}\",\"pane_current_path\":\"#{pane_current_path}\", \"project\":\"${git_full_name}\", \"path\":\"${repo_url}\", \"file\":\"${title}/\", \"branch\":\"${git_branch}\"}");
    ## language: "unknown"
    ## file: "unknown" // but is set to 
    PAYLOAD="{\"timestamp\":\"$(gdate -Is)\",\"duration\":0,\"data\":$DATA}"
    echo "$PAYLOAD"
    HTTP_CODE=$(curl -X POST "${API_URL}/0/buckets/$BUCKET_ID/heartbeat?pulsetime=$PULSETIME" -H "accept: application/json" -H "Content-Type: application/json" -d "$PAYLOAD" -s -o $TMP_FILE -w %{http_code})
    if (( $HTTP_CODE != 200 )); then
        echo "Request failed"
        cat $TMP_FILE
    fi

    if [[ "$DEBUG" -eq "1" ]]; then
        cat $TMP_FILE
    fi
}


### MAIN POLL LOOP

declare -A act_last
declare -A act_current

init_bucket


### kill all old processes of this script
kill -9 $(pgrep -f ${BASH_SOURCE[0]} | grep -v $$)



while [ true ]
do
    #clear
	sessions=$(tmux list-sessions | awk '{print $1}')
	if (( $? != 0 )); then
        echo "tmux list-sessions ERROR: $?"
    fi
	if (( $? == 0 )); then
        LAST_IFS=$IFS
        IFS='
'
        for sess in ${sessions}; do
            act_time=$(tmux display -t $sess -p '#{session_activity}')
            if [[ ! -v "act_last[$sess]" ]];  then
                act_last[$sess]='0'
            fi
            if (( $act_time > ${act_last[$sess]} )); then
                # echo "###> "$sess' '$(date -Iseconds)'    '$act_time' '$act_last[$sess] ##  >> tmux-sess-act.log
                log_to_bucket $sess
            fi
            act_current[$sess]=$act_time
        done
        IFS=$LAST_IFS
        # copy arrays
        unset R
        declare -A act_last
        for sess in "${!act_current[@]}"; do
            act_last[$sess]=${act_current[$sess]}
        done
	fi

	sleep $POLL_INTERVAL
done
