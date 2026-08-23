import json
from pathlib import Path

class ProgressStore:
    def __init__(self,path):
        self.path=Path(path); self.data=self._load()
    def _load(self):
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception: return {"lessons":{},"words":{},"reviews":{}}
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True); self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding="utf-8")
    def lesson(self,video_id): return self.data["lessons"].setdefault(video_id,{"views":0,"completed":False,"sentences":{},"score":0})
    def mark_view(self,video_id):
        x=self.lesson(video_id); x["views"]+=1; self.save()
    def mark_sentence(self,video_id,index):
        self.lesson(video_id)["sentences"][str(index)]=True; self.save()
