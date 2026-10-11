import pytest
from app.database import SessionLocal
from app.services.search import execute_hybrid_search


@pytest.fixture(scope="module")
def db_session():
    db = SessionLocal()
    yield db
    db.close()


def test_query_photo_editor_for_linux(db_session):
    """
    Query: 'open-source photo editor for Linux'
    Requirements:
    - Platform constraint 'linux' and license constraint 'confirmed_open_source' extracted and enforced.
    - True image/photo editors (gimp, rawtherapee, darktable, krita, inkscape) returned.
    - Spurious developer tools (vscodium, dbeaver) and non-linux apps must NOT pollute top results.
    """
    results, meta = execute_hybrid_search(db_session, "open-source photo editor for Linux", limit=5)
    assert len(results) >= 3

    assert meta["applied_filters"]["platform"] == "linux"
    assert meta["applied_filters"]["license_state"] == "confirmed_open_source"

    top_slugs = [r["app"].slug for r in results]
    assert top_slugs[0] in ["gimp", "rawtherapee"]

    # Verify all returned apps satisfy the constraints
    for r in results:
        app = r["app"]
        assert "linux" in [p.lower() for p in (app.platforms or [])]
        assert app.license_state == "confirmed_open_source"

    # Verify no unrelated developer tools in top results
    assert "vscodium" not in top_slugs
    assert "dbeaver" not in top_slugs


def test_query_organize_and_backup_my_photos(db_session):
    """
    Query: 'organize and back up my photos'
    Requirements:
    - Resolves phrasal verb 'back up' to backup and 'organize photos' to photo organizers.
    - Immich (which has direct capability for photo organization and backup) ranks #1.
    - 3D creation suites (blender) and music players must not pollute top results.
    """
    results, meta = execute_hybrid_search(db_session, "organize and back up my photos", limit=5)
    assert len(results) >= 3

    top_slugs = [r["app"].slug for r in results]
    assert top_slugs[0] == "immich"

    # All top results should be photo management or backup utilities
    allowed = {"immich", "kopia", "borgbackup", "restic", "duplicati", "darktable", "rawtherapee", "gimp"}
    for slug in top_slugs[:3]:
        assert slug in allowed

    assert "blender" not in top_slugs[:3]
    assert "strawberry" not in top_slugs[:3]


def test_query_find_duplicate_audio_files(db_session):
    """
    Query: 'find duplicate audio files'
    Requirements:
    - Czkawka (direct capability for duplicate audio detection) ranks #1.
    - Generic audio players that cannot find duplicates must not outrank the dedicated duplicate tool.
    """
    results, meta = execute_hybrid_search(db_session, "find duplicate audio files", limit=5)
    assert len(results) >= 1

    top_slugs = [r["app"].slug for r in results]
    assert top_slugs[0] == "czkawka"
    assert "direct_capability_match" in results[0]["sources"]


def test_query_music(db_session):
    """
    Query: 'music'
    Requirements:
    - Returns primary audio and music applications (musescore, strawberry, kodi, jellyfin, ardour, audacity, vlc).
    - All top 5 apps must belong to Music & Audio domain.
    """
    results, meta = execute_hybrid_search(db_session, "music", limit=5)
    assert len(results) >= 5

    valid_music_apps = {"musescore", "strawberry", "kodi", "jellyfin", "ardour", "audacity", "vlc", "lmms", "mpv"}
    top_slugs = [r["app"].slug for r in results]
    for slug in top_slugs:
        assert slug in valid_music_apps


def test_query_storage(db_session):
    """
    Query: 'storage'
    Requirements:
    - Returns core storage, cleanup, backup, and archive applications.
    - Note-taking tools (logseq) must not rank in top storage results.
    """
    results, meta = execute_hybrid_search(db_session, "storage", limit=5)
    assert len(results) >= 5

    valid_storage_apps = {
        "kopia", "duplicati", "nextcloud-desktop", "cyberduck", "bleachbit",
        "czkawka", "restic", "borgbackup", "peazip", "7-zip", "syncthing"
    }
    top_slugs = [r["app"].slug for r in results]
    for slug in top_slugs:
        assert slug in valid_storage_apps

    assert "logseq" not in top_slugs


@pytest.mark.parametrize("typo_query,expected_top_slug", [
    ("audaciti", "audacity"),
    ("czkawk", "czkawka"),
    ("imich photos", "immich"),
    ("kopya backup", "kopia"),
    ("blechbit", "bleachbit"),
    ("vls media", "vlc"),
    ("obz studio recorder", "obs-studio"),
])
def test_typo_tolerant_queries(db_session, typo_query, expected_top_slug):
    """
    Typo queries must retrieve the target application at rank #1 via trigram similarity
    and named-entity relevance weighting.
    """
    results, meta = execute_hybrid_search(db_session, typo_query, limit=5)
    assert len(results) >= 1
    assert results[0]["app"].slug == expected_top_slug


def test_platform_constraints_enforcement(db_session):
    """
    Ensure platform constraints are strictly enforced without leakage:
    - macOS query must never return apps that don't support macOS (e.g. BleachBit).
    - Windows query must never return Windows-incompatible apps (e.g. BorgBackup).
    """
    macos_results, meta_mac = execute_hybrid_search(db_session, "backup tool for macos", limit=10)
    assert len(macos_results) >= 1
    assert meta_mac["applied_filters"]["platform"] == "macos"
    for r in macos_results:
        assert "macos" in [p.lower() for p in (r["app"].platforms or [])]
    assert "bleachbit" not in [r["app"].slug for r in macos_results]

    win_results, meta_win = execute_hybrid_search(db_session, "video broadcast for windows", limit=10)
    assert len(win_results) >= 1
    assert meta_win["applied_filters"]["platform"] == "windows"
    for r in win_results:
        assert "windows" in [p.lower() for p in (r["app"].platforms or [])]


def test_license_constraints_enforcement(db_session):
    """
    Ensure license state constraints exclude non-open-source apps:
    - 'open-source' constraint must drop 'source_available' and 'unresolved' items.
    """
    results, meta = execute_hybrid_search(db_session, "open-source backup", limit=20)
    assert meta["applied_filters"]["license_state"] == "confirmed_open_source"
    for r in results:
        assert r["app"].license_state == "confirmed_open_source"

    slugs = [r["app"].slug for r in results]
    assert "source-available-demo" not in slugs
    assert "unresolved-demo-tool" not in slugs


@pytest.mark.parametrize("unknown_query", [
    "quantum superconductor teleportation",
    "astrological telepathic crystal tuning",
    "interstellar spacecraft warp drive firmware",
    "xyz123 nonexisting software tool",
])
def test_unknown_queries_yield_zero_results(db_session, unknown_query):
    """
    For completely out-of-domain / unknown queries, the discovery engine must NOT
    fabricate results or return low-quality unrelated records.
    """
    results, meta = execute_hybrid_search(db_session, unknown_query, limit=10)
    assert len(results) == 0
