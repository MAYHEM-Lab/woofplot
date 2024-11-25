# WoofPlot tests
```
Setup: 
Window1: redis-server
Window2: rq worker default

Window3:
Run Tests:
python utils.py tests/clean.json   		#clean out everything and exit

#load woof and dump them to stdout
python utils.py tests/args.json   		#cox/float, pz5/string

#test running background jobs
python utils.py tests/args1.json

#delete woof cox/float, reloads latest afterward
python utils.py tests/dwoof.json

#load woof seqno series pz5/string ⇒ change start and end to valid values returned from above dump
python utils.py tests/intv.json

```
