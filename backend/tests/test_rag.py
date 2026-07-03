import io

from app.rag.chunker import PageText, chunk_pages


def test_chunker_sections_and_pages():
    pages = [
        PageText(
            page=1,
            text="Chapter 1: Combat\n\n" + ("Attack rolls work like this. " * 40),
            headings=["Chapter 1: Combat"],
        ),
        PageText(
            page=2,
            text="Grappling\n\n" + ("When you want to grab a creature. " * 60),
            headings=["Grappling"],
        ),
    ]
    chunks = chunk_pages(pages)
    assert chunks, "should produce chunks"
    assert any("Combat" in c.section_path for c in chunks)
    assert any("Grappling" in c.section_path for c in chunks)
    grapple = [c for c in chunks if "Grappling" in c.section_path]
    assert all(c.page_start >= 1 for c in grapple)


def test_chunker_respects_target_size():
    pages = [PageText(page=1, text="\n\n".join(["Paragraph of text here."] * 400), headings=[])]
    chunks = chunk_pages(pages)
    assert len(chunks) > 1
    assert all(len(c.text) <= 3200 + 600 for c in chunks)  # target + slack


def test_chunker_empty():
    assert chunk_pages([]) == []
    assert chunk_pages([PageText(page=1, text="", headings=[])]) == []


def _tiny_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "House Rules of the Crimson Table", fontsize=20)
    page.insert_text(
        (72, 150),
        "Critical Fumbles\n"
        "Whenever a player rolls a natural 1 on an attack,\n"
        "they must roll on the fumble table and their weapon\n"
        "gains one notch of wear. Three notches break the\n"
        "weapon permanently.",
        fontsize=11,
    )
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def test_pdf_upload_ingest_and_search(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await app_client.post("/api/v1/campaigns", json={"name": "C"})).json()
    cid = campaign["id"]

    # SRD prose is pre-ingested: rules search works before any upload
    resp = await app_client.get(f"/api/v1/campaigns/{cid}/search?q=grappled condition")
    assert resp.status_code == 200
    assert any("SRD" in h["document_title"] for h in resp.json())

    # upload a homebrew PDF (BackgroundTasks run inline under ASGITransport)
    files = {"file": ("house-rules.pdf", _tiny_pdf_bytes(), "application/pdf")}
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/documents", files=files)
    assert resp.status_code == 200, resp.text

    resp = await app_client.get(f"/api/v1/campaigns/{cid}/documents")
    docs = {d["title"]: d for d in resp.json()}
    assert "house-rules" in docs
    assert docs["house-rules"]["status"] == "ready"
    assert docs["house-rules"]["chunk_count"] >= 1

    # the uploaded content is searchable with citation info
    resp = await app_client.get(f"/api/v1/campaigns/{cid}/search?q=fumble weapon notch")
    hits = resp.json()
    assert hits, "expected search hits for uploaded content"
    assert hits[0]["document_title"] == "house-rules"
    assert "notch" in hits[0]["text"]

    # non-PDF rejected
    files = {"file": ("notes.txt", b"plain text", "text/plain")}
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/documents", files=files)
    assert resp.status_code == 400

    # players can't upload
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post("/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]})
    files = {"file": ("sneaky.pdf", _tiny_pdf_bytes(), "application/pdf")}
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/documents", files=files)
    assert resp.status_code == 403


async def test_lookup_tool_book_kind(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await app_client.post("/api/v1/campaigns", json={"name": "C"})).json()
    scene = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "S", "dm_mode": "human"},
        )
    ).json()

    import app.ai.tools.core_tools  # noqa: F401  — populate the registry
    from app.ai.tools.registry import ToolContext, registry
    from app.db import get_sessionmaker
    from app.models import Campaign, Scene

    async with get_sessionmaker()() as db:
        campaign_row = await db.get(Campaign, campaign["id"])
        scene_row = await db.get(Scene, scene["id"])
        ctx = ToolContext(db=db, campaign=campaign_row, scene=scene_row)
        result = await registry.dispatch(
            ctx, "lookup", {"query": "grappled speed becomes 0", "kind": "book"}
        )
        assert result.ok, result.error
        assert result.data["passages"]
        assert "SRD" in result.data["passages"][0]["source"]
