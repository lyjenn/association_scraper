from scraper_app.workflow.extractors import ExtractBuffer


def test_merge_sections_and_tables():
    buf = ExtractBuffer()
    buf.merge_label_values(
        "General Profile Information",
        {"Profile Type": "Member", "Herd Prefix": "BRAY"},
    )
    buf.merge_label_values("General Profile Information", {"Official Profile ID": "10179"})
    buf.set_table(
        "Contacts",
        [{"Name": "Reldon Bray", "Phone": "555-0100"}],
    )
    data = buf.to_dict()
    assert data["General Profile Information"]["Profile Type"] == "Member"
    assert data["General Profile Information"]["Official Profile ID"] == "10179"
    assert data["Contacts"][0]["Name"] == "Reldon Bray"


def test_different_association_shapes():
    a = ExtractBuffer()
    a.merge_label_values("General Profile Information", {"Herd Prefix": "BRAY"})
    b = ExtractBuffer()
    b.merge_label_values("Breeder Information", {"Farm Name": "ABC Ranch"})
    b.set_table("Animals", [{"Registration": "123", "Sex": "Bull"}])
    assert "Herd Prefix" in a.to_dict()["General Profile Information"]
    assert "Farm Name" in b.to_dict()["Breeder Information"]
    assert "Animals" in b.to_dict()
    assert "Herd Prefix" not in str(b.to_dict())
