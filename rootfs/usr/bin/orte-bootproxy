#!/bin/sh
#
# Copyright (c) 2009      Los Alamos National Security, LLC. All rights reserved
# Copyright (c) 2009      Cisco Systems, Inc.  All rights reserved.
#

if test $# -lt 1; then
    echo "orte-bootproxy.sh: for OMPI internal use only"
    exit 1
fi

# take the first arg
var=$1

# if the var is CLEANUP, then we are in cleanup mode
if [ "${var}" = "CLEANUP" ]; then
    shift 1
    var=$1
    if [ -n "${var}" ] && [ "${var}" = "APPS" ]; then
        # kill specified apps
        shift 1
        var=$1
        # get the process table
        psout=`ps`
        # cycle through and look for the specified apps
        while [ -n "${var}" ] && [ "${var}" != "FILES" ]; do
            testvar=`echo "${psout}" | grep "${var}"`
            if [ -n "${testvar}" ]; then
#                echo "killall" "${var}"
                killall -TERM "${var}"
            fi
            shift 1
            var=$1
        done
        if [ -n "${var}" ]; then
            shift 1
            var=$1
            # remove specified files
            while [ -n "${var}" ]; do
                if [ -e "${var}" ]; then
#                    echo "rm" "${var}"
                    rm -f "${var}"
                fi
                shift 1
                var=$1
            done
        fi
    elif [ "${var}" = "FILES" ]; then
        # remove specified files
        shift 1
        var=$1
        while [ -n "${var}" ]; do
            if [ -e "${var}" ]; then
#                echo "rm" "${var}"
                rm -f "${var}"
            fi
            shift 1
            var=$1
        done
    fi
    # remove any session directories from this user
#    sdir="${TMPDIR}""openmpi-sessions-""${USER}""@"`hostname`"_0"
    sdir="/tmp/openmpi-sessions-""${USER}""@"`hostname`"_0"
    if [ -e "${sdir}" ]; then
#        echo "rm" "${sdir}"
        rm -rf "${sdir}"
    fi
    exit 0
fi

# push all MCA params to the environment
while [ "$(echo $var | awk  '{ string=substr($0, 1, 5); print string; }' )" = "OMPI_" ]; do
    if [ "$(echo $var | awk  '{ string=substr($0, 6, 6); print string; }' )" = "PREFIX" ]; then
        TMP_PATH=$(echo $var | awk  '{ string=substr($0, 1, 12); print string; }' )
        export LD_LIBRARY_PATH="$TMP_PATH"/lib:$LD_LIBRARY_PATH
        export PATH="$TMP_PATH"/bin:$PATH
    elif [ "$(echo $var | awk  '{ string=substr($0, 5, 4); print string; }' )" = "WDIR" ]; then
        cd "$(echo $var | awk  '{ string=substr($0, 1, 10); print string; }' )"
    else
        export $var
    fi
    shift 1
    var=$1
done

# extract the application to be executed
app=$1
shift 1

#exec the app with the remaining args
#echo "executing" "$app"
exec "$app" "$@"
