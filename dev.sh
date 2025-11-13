#!/usr/bin/env bash
# local development helper script

CONTAINERS=( "ots-db" "rabbitmq" ) # "mediamtx"

purp() { printf "\033[0;35m[$(basename "$0")] %s\033[0m\n" "$1"; }
red() { printf "\033[0;31m[$(basename "$0")] %s\033[0m\n" "$1"; }
grn() { printf "\033[0;32m[$(basename "$0")] %s\033[0m\n" "$1"; }
yel() { printf "\033[0;33m[$(basename "$0")] %s\033[0m\n" "$1"; }

# ensure dependencies (tmux optional)
deps=( "docker" "docker compose" "poetry" )
for dep in "${deps[@]}"; do
    if ! command -v $dep &> /dev/null; then
        echo "$dep could not be found, please install it."
        exit 1
    fi
done

# parse args
if [[ "$1" == "clean" ]]; then
    purp "Cleaning up development environment..."
    docker compose down -v
    tmux kill-session -t OTS 2>/dev/null

    if [[ -d "./ots" ]]; then
        read -rp "$(yel "Do you also want to remove the OTS data folder? (y/N): ")" confirm
        if [[ "$confirm" =~ ^[Yy](es)?$ ]]; then
            rm -rf ./ots
            echo "OTS data folder removed."
        else
            echo "OTS data folder not removed."
        fi
    fi

elif [[ "$1" == "start" ]]; then
    service="$2"

    purp "Starting docker containers..."
    if ! docker compose up -d; then
        red "Failed to start docker containers."
        exit 1
    fi

    purp "Syncing poetry dependencies..."
    if poetry lock && poetry sync; then
        grn "Poetry dependencies are up to date."
    else
        red "Failed to sync poetry dependencies."
        exit 1
    fi

    purp "Waiting for containers to be healthy..."
    i=0
    max_wait=30
    delay=2
    while true; do
        all_healthy=true
        for container in "${CONTAINERS[@]}"; do
            status=$(docker inspect --format='{{.State.Health.Status}}' "$container")
            if [ "$status" != "healthy" ]; then
                all_healthy=false
                printf "%s is %s\\r" "$container" "$status"
                # atleast try 3 times before aborting on unhealthy
                if [ $i -gt 3 ] && [ "$status" == "unhealthy" ]; then
                    echo "Container $container is unhealthy. Aborting."
                    exit 1
                fi
                break
            fi
        done

        if [ "$all_healthy" = true ]; then
            grn "All containers are healthy"
            break
        fi

        i=$((i+1))
        if [ $i -gt $max_wait ]; then
            red "Containers failed to become healthy after $((max_wait * delay)) seconds. Aborting."
            exit 1
        fi
        sleep $delay
    done

    # start services: use tmux if available, otherwise prompt which single service to run
    SESSION="OTS"
    export $(cat .env.dev | xargs)

    if [[ -z "$service" ]] && command -v tmux &>/dev/null; then
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            purp "Attaching to existing tmux session '$SESSION'..."
            tmux attach -t "$SESSION"
            exit 0
        fi
        tmux new-session -d -s "$SESSION"
        tmux rename-window -t "$SESSION:0" 'server'

        # # server
        tmux send-keys -t "$SESSION" 'poetry run opentakserver' C-m

        # workers window with two panes
        tmux new-window -t "$SESSION" -n workers
        tmux split-window -t "$SESSION:workers" -h
        tmux send-keys -t "$SESSION:workers.0" 'poetry run eud_handler' C-m
        tmux send-keys -t "$SESSION:workers.1" 'poetry run cot_parser' C-m

        tmux select-window -t "$SESSION:server"
        tmux attach -t "$SESSION"
    else
        # Handle both CLI arg and interactive selection
        if [[ -z "$service" ]]; then
            yel "tmux not found - select a service to run:"
            PS3="Select service (1-3): "
            select service in "opentakserver" "eud_handler" "cot_parser"; do
                case $service in
                    "opentakserver"|"eud_handler"|"cot_parser")
                        break
                        ;;
                    *)
                        echo "Invalid option. Choose 1-3."
                        ;;
                esac
            done
        fi

        case $service in
            "opentakserver"|"eud_handler"|"cot_parser")
                purp "Starting $service..."
                poetry run "$service"
                ;;
            *)
                red "Invalid service: $service"
                echo "Valid services: opentakserver, eud_handler, cot_parser"
                exit 1
                ;;
        esac
    fi

else
    echo "Usage: $0 (start [service]|clean) "
    exit 1
fi