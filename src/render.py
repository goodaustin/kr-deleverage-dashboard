"""把 IND dict 注入 index.html 的 /*IND-START*/.../*IND-END*/ 之間。只動這一段。"""
import json, re, pathlib

_PAT = re.compile(r'/\*IND-START\*/const IND = .*?;/\*IND-END\*/', re.S)

def render(ind: dict, html_path: str = "index.html") -> None:
    p = pathlib.Path(html_path)
    html = p.read_text(encoding="utf-8")
    payload = json.dumps(ind, ensure_ascii=False, separators=(",", ":"))
    repl = f'/*IND-START*/const IND = {payload};/*IND-END*/'
    new = _PAT.sub(lambda _: repl, html, count=1)
    if new == html and _PAT.search(html) is None:
        raise RuntimeError("IND markers not found in " + html_path)
    p.write_text(new, encoding="utf-8")
