#/bin/bash

 ./docker-compose -f docker-compose_reverse.yml build
 ./docker-compose -f docker-compose_reverse.yml up -d
 #./docker-compose -f docker-compose_reverse.yml down