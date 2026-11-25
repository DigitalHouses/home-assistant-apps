"""Ingress visual contract: Network-style chrome, full-width Aqara layout."""
from pathlib import Path
from unittest import TestCase

WEB = Path(__file__).resolve().parents[1] / "rootfs/app/electrica/web"

class IngressStyleTests(TestCase):
    def test_network_reference_palette_and_header(self):
        html=(WEB/"index.html").read_text()
        css=(WEB/"style.css").read_text()
        for item in ("app-header","brand","app-version","devices-nav","scan"):
            self.assertIn(item,html)
        for color in ("#111b29","#192b41","#284059","#536e83","#137b78","#26b6a5","#82efc7","#ffd094"):
            self.assertIn(color,css)
        self.assertIn("main{padding:14px 22px 22px;width:100%",css)
        self.assertIn(".bindings{display:flex;gap:8px 16px;flex-wrap:wrap",css)
        self.assertNotIn("max-width:1250px",css)

    def test_target_type_icons_and_existing_actions(self):
        js=(WEB/"app.js").read_text()
        for kind in ("switch","rgb","cct","dimmer","bulb"):
            self.assertIn('"'+kind+'"',js)
        self.assertIn('targetIcon(t,id)',js)
        self.assertIn('targetIcon(t,a.entity_id)',js)
        self.assertIn('api("scan",{})',js)
        self.assertIn('api("save",',js)
        self.assertIn('draft.disabled_actions',js)

    def test_import_preserves_raw_document_for_strict_server_validation(self):
        js=(WEB/"app.js").read_text()
        self.assertIn("const documentText=await file.text()",js)
        self.assertIn('JSON.parse(documentText)',js)
        self.assertIn("+documentText+",js)
        self.assertIn("body:raw?data:JSON.stringify(data)",js)
