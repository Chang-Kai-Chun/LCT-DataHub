"""FastAPI 路由測試：以實際測試檔走完 A、B、C 的流程，並檢查錯誤回應格式；另測使用者與專案（G-4）。"""
import io
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from lct_datahub.api.main import create_app

ROOT = Path(__file__).resolve().parent.parent
JV_DIR, JD_DIR, EQE_DIR = ROOT / "test_for_develop" / "JV_test_file", ROOT / "test_for_develop" / "JD_test_file", ROOT / "test_for_develop" / "EQE_test_file"
PNG_MAGIC = b"\x89PNG"
USER, PROJECT = "Tester", "2026-11 測試 1 mol%"  # 專案名稱含中文、空格與 %，測試網址編碼
PROJECT_CONDITIONS = ["Ref", "0.2%", "A", "B"]
UPLOAD_PARAMS = {"user": USER, "project": PROJECT}


@pytest.fixture
def client(tmp_path) -> TestClient:
    """每個測試用自己的資料資料夾，並先建立一位使用者與一個專案。"""
    c = TestClient(create_app(tmp_path))
    assert c.post("/api/users", json={"name": USER}).status_code == 200
    res = c.post(f"/api/users/{USER}/projects", json={"name": PROJECT, "conditions": PROJECT_CONDITIONS})
    assert res.status_code == 200
    return c


def _project_url() -> str:
    """專案的 API 網址（名稱做 URL 編碼）。"""
    return f"/api/users/{quote(USER, safe='')}/projects/{quote(PROJECT, safe='')}"


def _upload(client: TestClient, section: str, paths: list[Path]):
    """上傳檔案到測試專案並回傳回應。"""
    files = [("files", (p.name, p.read_bytes())) for p in paths]
    return client.post(f"/api/{section}/jobs", files=files, params=UPLOAD_PARAMS)


def _files(folder: Path) -> list[Path]:
    """資料夾內所有檔案（含不接受的副檔名，測試略過機制）。"""
    return sorted(p for p in folder.iterdir() if p.is_file())


needs = lambda folder: pytest.mark.skipif(not folder.exists(), reason=f"沒有 {folder.name}")  # noqa: E731


# ---------- 共用 ----------
def test_health(client):
    """健康檢查。"""
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("job_id", ["20261106-000000-00000000", "..%5C..%5Cetc", "abc"])
def test_unknown_job_is_404(client, job_id):
    """不存在或格式不符的工作編號（含 ..\\ 路徑穿越）：404。"""
    res = client.get(f"/api/eqe/jobs/{job_id}")
    assert res.status_code == 404 and res.json()["kind"] == "not_found"


def test_upload_rejects_no_valid_files_and_duplicates(client):
    """沒有可處理的檔案、檔名重複：400。"""
    res = client.post("/api/eqe/jobs", files=[("files", ("a.jpg", b"x"))], params=UPLOAD_PARAMS)
    assert res.status_code == 400 and res.json()["kind"] == "input"
    files = [("files", ("a.txt", b"x")), ("files", ("a.txt", b"y"))]
    res = client.post("/api/eqe/jobs", files=files, params=UPLOAD_PARAMS)
    assert res.status_code == 400 and "重複" in res.json()["message"]


def test_bad_file_returns_file_error(client):
    """內容無法辨識：422，附檔名、原因、期望、實際；檔名的路徑部分會被去掉。"""
    res = client.post("/api/eqe/jobs", files=[("files", ("../evil.txt", b"hello\tworld"))], params=UPLOAD_PARAMS)
    body = res.json()
    assert res.status_code == 422 and body["kind"] == "file"
    assert body["filename"] == "evil.txt" and body["reason"] and body["expected"] and body["actual"]


# ---------- C EQE ----------
@needs(EQE_DIR)
def test_eqe_flow(client):
    """上傳 → 改名 → 畫圖 → 下載（兩種儀器打包成 zip）。"""
    res = _upload(client, "eqe", _files(EQE_DIR))
    assert res.status_code == 200
    job = res.json()
    names = [c["name"] for c in job["curves"]]
    assert len(names) == 40 and "S1" in names
    url = f"/api/eqe/jobs/{job['job_id']}"

    # 改名：S1 → X1；GET 也看得到；不合理的改名 400
    renamed = client.put(f"{url}/names", json={"names": {"S1": "X1"}}).json()
    assert "X1" in [c["name"] for c in renamed["curves"]]
    assert client.get(url).json() == renamed
    assert client.put(f"{url}/names", json={"names": {"S1": "  "}}).status_code == 400

    # 畫圖：PNG；名稱不存在或範圍不合理 400
    res = client.post(f"{url}/plots/eqe", json={"names": ["X1", names[-1]], "x_range": [300, 1100]})
    assert res.status_code == 200 and res.content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/rplot", json={"names": ["X1"]}).content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/eqe", json={"names": ["S1"]}).status_code == 400  # 已改名
    assert client.post(f"{url}/plots/eqe", json={"names": ["X1"], "x_range": [900, 300]}).status_code == 400

    # 下載：兩份 Excel 打包成 zip
    res = client.get(f"{url}/excel")
    assert res.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(res.content)).namelist()) == ["Eqe_Old.xlsx", "Eqe_PD-QE.xlsx"]


@needs(EQE_DIR)
def test_eqe_naming_and_grouping(client):
    """舊型樣品未命名不能分組；命名後依樣品分組（同 B 區）；改名使樣品組成改變時分組清除。"""
    job = _upload(client, "eqe", _files(EQE_DIR)).json()
    url = f"/api/eqe/jobs/{job['job_id']}"
    olds = job["unnamed"]
    assert olds == [f"S{i}" for i in range(1, 14)]
    assert {c["device"] for c in job["curves"] if c["name"].startswith("G1-")} == {"G1"}
    even = {"mode": "平均分配", "names": ["A", "B"]}
    res = client.post(f"{url}/grouping/preview", json=even)
    assert res.status_code == 400 and "命名" in res.json()["message"]

    # 舊型命名為 G30-1…G30-13 後可以分組
    names = {s: f"G30-{i}" for i, s in enumerate(olds, start=1)}
    named = client.put(f"{url}/names", json={"names": names}).json()
    assert named["unnamed"] == [] and "G30" in named["devices"]
    preview = client.post(f"{url}/grouping/preview", json=even).json()
    saved = client.put(f"{url}/conditions", json={"conditions": preview["conditions"]}).json()
    assert saved["settings"]["conditions"] == preview["conditions"]

    # 只改 pixel 編號（樣品組成不變）：分組保留；改成新樣品 G31：分組清除
    kept = client.put(f"{url}/names", json={"names": {**names, olds[0]: "G30-99"}}).json()
    assert kept["settings"]["conditions"] == preview["conditions"]
    moved = client.put(f"{url}/names", json={"names": {**names, olds[0]: "G31-1"}}).json()
    assert moved["settings"]["conditions"] is None


# ---------- B 暗電流 ----------
@needs(JD_DIR)
def test_dark_flow(client):
    """上傳 → 面積檢查 → 偏移與指定面積 → 畫圖 → 下載。"""
    job = _upload(client, "dark", _files(JD_DIR)).json()
    url = f"/api/dark/jobs/{job['job_id']}"
    # PD-QE 檔內 4.5 mm²；明志由 |I|/J 反推也是 0.045 cm²，所以一致
    assert len(job["curves"]) == 58 and job["area_report"]["uniform_value"] == 0.045
    assert job["settings"] == {"area": None, "shift_mode": "保持原始", "area_confirmed": False, "conditions": None, "extract_bias": 0.0}
    assert not any(c["is_shifted"] for c in job["curves"])

    shifted = client.put(f"{url}/settings", json={"shift_mode": "偏移到 0 V", "area": 0.05}).json()
    assert sum(c["is_shifted"] for c in shifted["curves"]) == 40
    assert shifted["settings"]["area_confirmed"]
    assert {c["area"] for c in shifted["curves"]} == {0.05}
    assert client.put(f"{url}/settings", json={"area": 0}).status_code == 400

    names = [c["name"] for c in shifted["curves"][:3]]
    res = client.post(f"{url}/plots/dark", json={"names": names, "y_range": [1e-10, 1e-2]})
    assert res.content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/dark", json={"names": names, "y_range": [0, 1]}).status_code == 400

    res = client.get(f"{url}/excel")
    assert res.headers["content-type"] == "application/zip"


@needs(JD_DIR)
def test_dark_extract(client):
    """B-4：擷取值（偏移後 Rsh＝儀器 Rs 對照）；選擇電壓會存檔；不支援的電壓 422。"""
    job = _upload(client, "dark", _files(JD_DIR)).json()
    url = f"/api/dark/jobs/{job['job_id']}"
    ext = client.get(f"{url}/extract").json()
    assert ext["bias"] == 0.0 and ext["biases"] == [0.0, -0.1, -0.5] and len(ext["rows"]) == 58
    row = next(r for r in ext["rows"] if r["name"] == "G1-3")
    assert row["rsh"] == pytest.approx(row["reference_rsh"], rel=1e-3) and set(row["jd"]) == {"0", "-0.1", "-0.5"}
    client.put(f"{url}/settings", json={"shift_mode": "偏移到 0 V"})
    shifted = {r["name"]: r for r in client.get(f"{url}/extract").json()["rows"]}
    assert shifted["G14-2"]["rsh"] == pytest.approx(4.851e7, rel=1e-3)  # 儀器 Rs 欄
    assert shifted["G14-2"]["rsh"] == pytest.approx(shifted["G14-2"]["reference_rsh"], rel=1e-3)
    assert client.put(f"{url}/extract-bias", json={"bias": -0.1}).json()["bias"] == -0.1
    assert client.get(url).json()["settings"]["extract_bias"] == -0.1
    assert client.put(f"{url}/extract-bias", json={"bias": -0.3}).status_code == 422


@needs(JD_DIR)
def test_dark_grouping(client):
    """元件分組：預填 → 確認（須全部分配）；改面積、偏移不會清掉分組。"""
    job = _upload(client, "dark", _files(JD_DIR)).json()
    url = f"/api/dark/jobs/{job['job_id']}"
    devices = job["devices"]
    # 明志的 G1 REF-1_330 K 取開頭代號，與 PD-QE 的 G1-x 同一個元件
    assert "G1" in devices and devices == sorted(devices, key=lambda d: int(d[1:]))
    assert {c["device"] for c in job["curves"] if c["name"].startswith(("G1-", "G1 "))} == {"G1"}

    preview = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "B"]}).json()
    assert [c["name"] for c in preview["conditions"]] == ["A", "B"] and preview["unassigned"] == []
    assert sorted(sum((c["samples"] for c in preview["conditions"]), [])) == sorted(devices)

    # 未全部分配：400；全部分配：存檔
    half = {"conditions": [{"name": "A", "samples": devices[:2]}]}
    assert client.put(f"{url}/conditions", json=half).status_code == 400
    saved = client.put(f"{url}/conditions", json={"conditions": preview["conditions"]}).json()
    assert saved["settings"]["conditions"] == preview["conditions"]

    # 改面積與偏移後，分組仍在
    after = client.put(f"{url}/settings", json={"area": 0.05, "shift_mode": "偏移到 0 V"}).json()
    assert after["settings"]["conditions"] == preview["conditions"]


@needs(JD_DIR)
def test_dark_upload_skips_excel_without_abs(client):
    """上傳時 Excel 檔名沒有 _abs 的略過（列在 skipped），其餘照常讀取。"""
    txt = next(p for p in JD_DIR.iterdir() if p.suffix == ".txt")
    files = [("files", (txt.name, txt.read_bytes())), ("files", ("no_mark.xlsx", b"x")), ("files", ("~$t_abs.xlsx", b"x"))]
    job = client.post("/api/dark/jobs", files=files, params=UPLOAD_PARAMS).json()
    assert job["skipped"] == ["no_mark.xlsx", "~$t_abs.xlsx"]
    assert {c["source"] for c in job["curves"]} == {txt.name}
    # 只有不符合規則的檔案：400
    res = client.post("/api/dark/jobs", files=[("files", ("no_mark.xls", b"x"))], params=UPLOAD_PARAMS)
    assert res.status_code == 400 and res.json()["kind"] == "input"


# ---------- A JV ----------
@needs(JV_DIR)
def test_jv_flow(client):
    """上傳 → 分組 → Box 表、篩選、手動保留 → Box 圖、JV 曲線圖 → 下載。"""
    res = _upload(client, "jv", _files(JV_DIR))
    assert res.status_code == 200
    job = res.json()
    url = f"/api/jv/jobs/{job['job_id']}"
    assert len(job["files"]) == 18 and len(job["samples"]) == 9
    assert any(name.endswith(".jpg") for name in job["skipped"])  # 只接受 csv

    # 尚未分組時不能做 Box
    assert client.post(f"{url}/box/table", json={}).status_code == 400

    # 預填：自動每 4 個一組，名稱依序取專案條件；平均分配名稱不可重複、須在專案條件中
    preview = client.post(f"{url}/grouping/preview", json={"mode": "自動"}).json()
    assert [len(c["samples"]) for c in preview["conditions"]] == [4, 4, 1] and preview["unassigned"] == []
    assert [c["name"] for c in preview["conditions"]] == PROJECT_CONDITIONS[:3]
    bad = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "A"]})
    assert bad.status_code == 400
    outside = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "Z"]})
    assert outside.status_code == 400 and "Z" in outside.json()["message"]
    assert job["project_conditions"] == PROJECT_CONDITIONS

    # 確認分組：有未分配樣品時 400；完整時存檔
    partial = {"conditions": [{"name": "Ref", "samples": job["samples"][:3]}]}
    assert client.put(f"{url}/conditions", json=partial).status_code == 400
    full = {"conditions": [
        {"name": "Ref", "samples": job["samples"][:4]},
        {"name": "0.2%", "samples": job["samples"][4:]},
    ]}
    confirmed = client.put(f"{url}/conditions", json=full).json()
    assert [c["name"] for c in confirmed["settings"]["conditions"]] == ["Ref", "0.2%"]
    assert confirmed["missing"] == []

    # Box 表：範圍篩選與手動保留
    rows = client.post(f"{url}/box/table", json={"mode": "FW"}).json()
    assert rows and all(r["Keep"] for r in rows) and {r["Direction"] for r in rows} == {"FW"}
    filtered = client.post(
        f"{url}/box/table", json={"ranges": {"Efficiency (%)": {"minimum": 1000}}, "keep": {"0": True}},
    ).json()
    assert filtered[0]["Keep"] and not any(r["Keep"] for r in filtered[1:])

    res = client.post(f"{url}/box/plot", json={"param": "Voc (V)", "mode": "FW＋RV"})
    assert res.content.startswith(PNG_MAGIC)
    res = client.post(f"{url}/curves/plot", json={"samples": job["samples"][:2], "directions": ["FW", "RV"]})
    assert res.content.startswith(PNG_MAGIC)

    # 指定面積：Jsc 依比例重算
    before = client.post(f"{url}/box/table", json={}).json()[0]["Jsc (mA/cm^2)"]
    area = confirmed["area_report"]["values"][0]
    client.put(f"{url}/area", json={"area": area * 2})
    after = client.post(f"{url}/box/table", json={}).json()[0]["Jsc (mA/cm^2)"]
    assert after == pytest.approx(before / 2)
    assert client.put(f"{url}/area", json={"area": -1}).status_code == 400

    res = client.get(f"{url}/excel", params={"directions": ["FW", "RV"]})
    assert res.headers["content-type"].startswith("application/vnd.openxmlformats")


# ---------- G-4 使用者與專案 ----------
def test_users(client):
    """使用者清單掃資料夾；名稱重複（不分大小寫）或含不允許的字元 400。"""
    assert client.get("/api/users").json() == [USER]
    assert client.post("/api/users", json={"name": "小明"}).json() == ["Tester", "小明"]
    assert client.post("/api/users", json={"name": "tester"}).status_code == 400
    for bad in ["", "a/b", "a:b", "..", "CON"]:
        assert client.post("/api/users", json={"name": bad}).status_code == 400, bad


def test_projects(client):
    """建立、列出、取得專案；找不到使用者或專案 404；上傳專案不存在 404。"""
    assert client.post(f"/api/users/{USER}/projects", json={"name": PROJECT.upper()}).status_code == 400
    dup = client.post(f"/api/users/{USER}/projects", json={"name": "P2", "conditions": ["Ref", "ref"]})
    assert dup.status_code == 400
    client.post(f"/api/users/{USER}/projects", json={"name": "P2"})
    names = [p["name"] for p in client.get(f"/api/users/{USER}/projects").json()]
    assert sorted(names) == sorted([PROJECT, "P2"])
    project = client.get(_project_url()).json()
    assert project["conditions"] == PROJECT_CONDITIONS and project["jobs"] == {}
    assert project["updated"] >= project["created"]  # 最後修改時間（ISO 字串可直接比較）

    assert client.get("/api/users/nobody/projects").status_code == 404
    assert client.get(f"/api/users/{USER}/projects/none").status_code == 404
    res = client.post("/api/eqe/jobs", files=[("files", ("a.txt", b"x"))], params={"user": USER, "project": "none"})
    assert res.status_code == 404


def test_project_grouping(client):
    """總覽分組：範圍展開、空白略過；條件不在專案中或樣品重複歸組 400；條件改名同步、使用中不能刪。"""
    body = {"conditions": [
        {"name": "Ref", "samples": "G1-G3, g7"}, {"name": "A", "samples": "G4"}, {"name": "B", "samples": ""},
    ]}
    project = client.put(f"{_project_url()}/grouping", json=body).json()
    assert project["grouping"] == [
        {"name": "Ref", "samples": ["G1", "G2", "G3", "G7"]}, {"name": "A", "samples": ["G4"]},
    ]
    bad = {"conditions": [{"name": "Z", "samples": "G1"}]}
    assert client.put(f"{_project_url()}/grouping", json=bad).status_code == 400
    dup = {"conditions": [{"name": "Ref", "samples": "G1"}, {"name": "A", "samples": "G1"}]}
    assert client.put(f"{_project_url()}/grouping", json=dup).status_code == 400

    # 改名 Ref → Base：總覽分組一起改；刪除使用中的 A：400
    edits = [{"old": c, "new": "Base" if c == "Ref" else c} for c in PROJECT_CONDITIONS]
    renamed = client.put(f"{_project_url()}/conditions", json={"conditions": edits}).json()
    assert [g["name"] for g in renamed["grouping"]] == ["Base", "A"]
    keep = [{"old": "Base", "new": "Base"}]
    res = client.put(f"{_project_url()}/conditions", json={"conditions": keep})
    assert res.status_code == 400 and "總覽" in res.json()["message"]


@needs(JD_DIR)
def test_project_grouping_samples_and_preview(client):
    """總覽分組：樣品清單為各區樣品聯集；預填同各區（樣品由前端送）；確定時可送樣品清單。"""
    assert client.get(f"{_project_url()}/samples").json() == []
    _upload(client, "dark", _files(JD_DIR))
    samples = client.get(f"{_project_url()}/samples").json()
    assert "G1" in samples and samples.index("G2") < samples.index("G10")  # 依數字大小排序

    body = {"mode": "平均分配", "names": ["Ref", "A"], "samples": samples}
    preview = client.post(f"{_project_url()}/grouping/preview", json=body).json()
    assert [c["name"] for c in preview["conditions"]] == ["Ref", "A"] and preview["unassigned"] == []
    saved = client.put(f"{_project_url()}/grouping", json={"conditions": preview["conditions"]}).json()
    assert saved["grouping"] == preview["conditions"]


def test_grouping_needs_project_conditions(client):
    """專案沒有條件時不能分組（400，提示到專案頁新增）。"""
    client.post(f"/api/users/{USER}/projects", json={"name": "Empty"})
    if not JD_DIR.exists():
        pytest.skip("沒有 JD_test_file")
    txt = next(p for p in JD_DIR.iterdir() if p.suffix == ".txt")
    files = [("files", (txt.name, txt.read_bytes()))]
    job = client.post("/api/dark/jobs", files=files, params={"user": USER, "project": "Empty"}).json()
    res = client.post(f"/api/dark/jobs/{job['job_id']}/grouping/preview", json={"mode": "自動"})
    assert res.status_code == 400 and "專案" in res.json()["message"]


@needs(JD_DIR)
def test_project_jobs_and_condition_edit(client):
    """上傳後專案記錄目前工作、重新上傳取代；條件改名會更新分組；刪除已使用的條件 400。"""
    first = _upload(client, "dark", _files(JD_DIR)).json()
    assert client.get(_project_url()).json()["jobs"] == {"dark": first["job_id"]}
    job = _upload(client, "dark", _files(JD_DIR)).json()
    assert client.get(_project_url()).json()["jobs"] == {"dark": job["job_id"]} != {"dark": first["job_id"]}

    url = f"/api/dark/jobs/{job['job_id']}"
    preview = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "B"]}).json()
    client.put(f"{url}/conditions", json={"conditions": preview["conditions"]})

    # 改名 A → New、刪除未使用的 0.2%、新增 C；分組中的 A 一起改成 New
    edits = [{"old": "Ref", "new": "Ref"}, {"old": "A", "new": "New"}, {"old": "B", "new": "B"}, {"old": None, "new": "C"}]
    project = client.put(f"{_project_url()}/conditions", json={"conditions": edits}).json()
    assert project["conditions"] == ["Ref", "New", "B", "C"]
    after = client.get(url).json()
    assert [c["name"] for c in after["settings"]["conditions"]] == ["New", "B"]
    assert after["project_conditions"] == ["Ref", "New", "B", "C"]

    # 刪除已被分組使用的 B：400，條件清單不變
    keep = [{"old": "Ref", "new": "Ref"}, {"old": "New", "new": "New"}]
    res = client.put(f"{_project_url()}/conditions", json={"conditions": keep})
    assert res.status_code == 400 and "B" in res.json()["message"]
    assert client.get(_project_url()).json()["conditions"] == ["Ref", "New", "B", "C"]
