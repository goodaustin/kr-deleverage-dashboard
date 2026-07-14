import json, re, pathlib, tempfile, shutil
from src.render import render

def test_render_injects_valid_json(tmp_path):
    html = tmp_path / "index.html"
    html.write_text('<script>/*IND-START*/const IND = {};/*IND-END*/\nconsole.log(IND);</script>')
    render({"composite": {"score": 45.8}, "asof": "20260710"}, str(html))
    txt = html.read_text()
    m = re.search(r'/\*IND-START\*/const IND = (.*?);/\*IND-END\*/', txt, re.S)
    assert m, "markers preserved"
    obj = json.loads(m.group(1))            # 必為合法 JSON
    assert obj["composite"]["score"] == 45.8
