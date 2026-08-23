def make_quiz(segments,index=0):
    if not segments: return None
    target=segments[index % len(segments)]
    words=target["text"].split()
    if len(words)<4: return {"type":"repeat","answer":target["text"]}
    hidden=max(1,len(words)//4); answer=" ".join(words[:hidden]); question=" ".join(["____" if i<hidden else w for i,w in enumerate(words)])
    return {"type":"fill_blank","question":question,"answer":answer,"sentence":target["text"],"start":target["start"]}

def spaced_repetition_box(score):
    score=max(0,min(5,int(score)))
    return {"score":score,"interval_days":[1,2,4,7,14,30][score]}
