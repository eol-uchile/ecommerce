#!/bin/bash

run(){
  python3 manage.py get_boleta_emissions "$1" --email && python3 manage.py boleta_emissions
}

if [[ ! -z $1 ]]; then
  run $1
else
  echo "Expected date in format YYYY-MM-DDT00:00:00 as first argument" 1>&2;
  echo "Using default of 2 days ago...";
  sleep 3 
  run $(date -d "2 day ago" +%Y-%m-%dT00:00:00)
fi
