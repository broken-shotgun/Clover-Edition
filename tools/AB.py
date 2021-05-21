import json
from random import shuffle
from numpy.random import beta
from numpy import greater
from numpy import mean
import subprocess
samplesize=1024*16

totals={'A':{'y':0, 'n':0}, 'B':{'y':0, 'n':0}}
while True:
    #a massive hack to avoid VRAM leak in torch
    responses = json.loads(subprocess.check_output(['python', 'genresponses.py', 'A']))
    lenres = len(responses)
    responses.extend(json.loads(subprocess.check_output(['python', 'genresponses.py', 'B'])))
    assert(len(responses)==lenres*2)

    print("\a")
    shuffle(responses)
    for r in responses:
        with open(r['prompt']) as file:
            p=file.read()
        print(p+r['output'])
        while True:
            v=input('Good? y/n:')
            if v=='y' or v=='n':
                break
        totals[r['name']][v]+=1
        print(totals)
        asamp=beta(totals['A']['y']+1, totals['A']['n']+1, samplesize)
        bsamp=beta(totals['B']['y']+1, totals['B']['n']+1, samplesize)
        prob=mean(greater(asamp, bsamp))
        print("The probability that A is better than B is:", prob)
        input("press enter to continue")
