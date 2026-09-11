#!/bin/sh

case "$1" in
    start)
        printf "Starting systeminfo: "
        # Executa em segundo plano redirecionando a saída
        /usr/bin/python3 /usr/bin/systeminfo.py > /var/log/systeminfo.log 2>&1 &
        if [ $? -eq 0 ]; then
            echo "OK"
        else
            echo "FAIL"
        fi
        ;;
    stop)
        printf "Stopping systeminfo: "
        killall python3
        echo "OK"
        ;;
    restart|reload)
        $0 stop
        $0 start
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac

exit 0