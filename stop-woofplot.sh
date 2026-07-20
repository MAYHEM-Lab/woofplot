#!/bin/bash

WOOFPLOT_DIR="/home/ubuntu/woofplot"
RQ="$WOOFPLOT_DIR/woofplotenv/bin/rq"

echo "Stopping woofplot..."

#
# Stop RQ workers cleanly.
#
echo "Stopping RQ workers..."

# SIGTERM asks RQ workers to shut down gracefully.
# Match only workers launched from this woofplot virtualenv.
PIDS=$(pgrep -f "$WOOFPLOT_DIR/woofplotenv/bin/rq worker")

if [ -n "$PIDS" ]; then
    echo "RQ worker PIDs: $PIDS"
    kill -TERM $PIDS

    # Give workers a few seconds to exit.
    for i in {1..10}; do
        if ! pgrep -f "$WOOFPLOT_DIR/woofplotenv/bin/rq worker" >/dev/null; then
            break
        fi
        sleep 1
    done

    # Kill anything that did not stop.
    PIDS=$(pgrep -f "$WOOFPLOT_DIR/woofplotenv/bin/rq worker")
    if [ -n "$PIDS" ]; then
        echo "Forcing remaining RQ workers to stop: $PIDS"
        kill -KILL $PIDS
    fi
else
    echo "No RQ workers running."
fi

#
# Stop woofplot Flask/backend server.
#
echo "Stopping woofplot server..."

PIDS=$(pgrep -f "python.*woofplot-server.py")

if [ -n "$PIDS" ]; then
    echo "Server PIDs: $PIDS"
    kill -TERM $PIDS

    sleep 2

    PIDS=$(pgrep -f "python.*woofplot-server.py")
    if [ -n "$PIDS" ]; then
        echo "Forcing remaining server processes to stop: $PIDS"
        kill -KILL $PIDS
    fi
else
    echo "No woofplot server running."
fi

echo
echo "Remaining woofplot processes:"
pgrep -af "woofplot.*(rq worker|woofplot-server)" || true

echo
echo "Woofplot stopped."
echo "Redis and PostgreSQL were left running."
