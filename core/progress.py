import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

class ProgressStore:
    def __init__(self,path):
        self.path=Path(path); self.data=self._load()
    def _load(self):
        defaults={"lessons":{},"words":{},"reviews":{}}
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data,dict):return defaults
            for key,value in defaults.items():
                if not isinstance(data.get(key),dict):data[key]=value
            return data
        except Exception:return defaults
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with NamedTemporaryFile("w",encoding="utf-8",dir=self.path.parent,delete=False) as tmp:
            json.dump(self.data,tmp,ensure_ascii=False,indent=2)
            temp_path=Path(tmp.name)
        os.replace(temp_path,self.path)
    def lesson(self,video_id):
        data=self.data["lessons"].setdefault(video_id,{})
        if not isinstance(data,dict):data={}; self.data["lessons"][video_id]=data
        data.setdefault("views",0); data.setdefault("completed",False); data.setdefault("score",0)
        if not isinstance(data.get("sentences"),dict):data["sentences"]={}
        return data
    def mark_view(self,video_id):
        x=self.lesson(video_id); x["views"]+=1; self.save()
    def mark_sentence(self,video_id,index):
        self.lesson(video_id)["sentences"][str(index)]=True; self.save()
