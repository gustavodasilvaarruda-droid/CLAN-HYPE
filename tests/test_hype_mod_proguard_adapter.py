"""No Java execution or network access: validate the isolated Fabric ProGuard adapter."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from services.hype_proguard_adapter import (
    AdapterError, _library_files, _validate_output,
    config_text, inspect_fabric_keep_classes,
)


def make_jar(*, cls=b"\\xca\\xfe\\xba\\xbeJavaBytes", metadata=None, mixin=None):
    metadata = metadata or {
        "id": "hype_test", "version": "1.0",
        "entrypoints": {"client": ["br.hype.ModEntry"]},
        "mixins": ["hype.mixins.json"],
    }
    mixin = mixin or {
        "package": "br.hype.mixin",
        "mixins": ["PlayerMixin"],
        "plugin": "br.hype.mixin.HypeMixinPlugin",
    }
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as out:
        out.writestr("fabric.mod.json", json.dumps(metadata))
        out.writestr("hype.mixins.json", json.dumps(mixin))
        out.writestr("br/hype/ModEntry.class", cls)
        out.writestr("br/hype/mixin/PlayerMixin.class", cls)
        out.writestr("br/hype/mixin/HypeMixinPlugin.class", cls)
    return stream.getvalue()


class ProguardAdapterTests(unittest.TestCase):
    def test_keeps_fabric_entrypoints_and_mixin_classes(self):
        keep = inspect_fabric_keep_classes(make_jar())
        self.assertIn("br.hype.ModEntry", keep)
        self.assertIn("br.hype.mixin.PlayerMixin", keep)
        self.assertIn("br.hype.mixin.HypeMixinPlugin", keep)

    def test_rejects_missing_mixin_class(self):
        with self.assertRaisesRegex(AdapterError, "missing"):
            inspect_fabric_keep_classes(
                make_jar(mixin={"package": "br.hype.mixin", "mixins": ["Missing"]})
            )

    def test_proguard_rules_preserve_runtime_and_disable_shrink(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output, lib = [Path(tmp) / x for x in ("input.jar", "output.jar", "lib.jar")]
            source.write_bytes(make_jar())
            lib.write_bytes(b"fake jar")
            rules = config_text(source, output, [str(lib)], ["br.hype.ModEntry"])
            self.assertIn("-dontshrink", rules)
            self.assertIn("-dontoptimize", rules)
            self.assertIn("-keep class br.hype.ModEntry { *; }", rules)
            self.assertIn("-keep @org.spongepowered.asm.mixin.Mixin class * { *; }", rules)
            self.assertNotIn("-ignorewarnings", rules)

    def test_no_binary_change_does_not_count_as_protection(self):
        with self.assertRaisesRegex(AdapterError, "No Java bytecode"):
            _validate_output(make_jar(), make_jar())

    def test_jar_runtime_resource_cannot_change(self):
        a = make_jar()
        b = make_jar(cls=b"changed", mixin={"package": "br.hype.mixin", "mixins": ["PlayerMixin"], "required": True})
        with self.assertRaisesRegex(AdapterError, "runtime resource"):
            _validate_output(a, b)

    def test_library_files_are_explicit_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "java.base.jmod"
            p.write_bytes(b"test")
            self.assertEqual(_library_files([tmp]), [str(p)])
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(AdapterError, "Provide"):
                _library_files([empty])


if __name__ == "__main__":
    unittest.main()
