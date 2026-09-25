from app.presentation import PublicationProfile


def test_obsolete_publication_profile_names_do_not_exist():
    for name in ("QUIET", "HIGH", "CRITICAL"):
        assert not hasattr(PublicationProfile, name)
