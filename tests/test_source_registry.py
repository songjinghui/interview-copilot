"""An installed source may implement only details or only feedback."""

import unittest
from tests.test_storage import feature
from tests.test_job_store import make_record
from interview_copilot.jobs.model import Capability, CapabilityStatus


class SourceRegistryTest(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, "interview_copilot.sources.registry")

    def register(
        self,
        registry,
        key="example",
        stage="product",
        state="ready",
        enabled=True,
        **ports,
    ):
        capability = Capability(
            CapabilityStatus.VERIFIED,
            "Fixture contract verified",
            evidence_ref="fixture://source",
        )
        descriptor = self.module.SourceDescriptor(
            key=key,
            display_name=key,
            adapter_version="1",
            enabled=enabled,
            connection_state=state,
            capabilities={
                name: self.module.RegisteredCapability(capability, stage=stage)
                for name in ports
            },
        )
        registry.register(descriptor, **ports)

    def test_detail_only_source_requires_no_search_method(self):
        class Detail:
            def read_job(self, ref):
                return make_record(source_key="example")

        registry = self.module.SourceRegistry()
        self.register(registry, read_job=Detail())
        self.assertEqual(
            registry.require("example", "read_job").read_job(None).source_key, "example"
        )
        with self.assertRaises(self.module.SourceError) as error:
            registry.require("example", "search_jobs")
        self.assertEqual(error.exception.reason, "unsupported")

    def test_feedback_only_source_requires_no_job_methods(self):
        class Feedback:
            def read_feedback(self, account, cursor):
                return (account, cursor)

        registry = self.module.SourceRegistry()
        self.register(registry, read_feedback=Feedback())
        self.assertEqual(
            registry.require("example", "read_feedback").read_feedback(
                "account-a", "cursor"
            ),
            ("account-a", "cursor"),
        )

    def test_external_evidence_is_not_product_availability(self):
        class Detail:
            def read_job(self, ref):
                return make_record()

        registry = self.module.SourceRegistry()
        self.register(registry, stage="external_sample", read_job=Detail())
        with self.assertRaises(self.module.SourceError) as error:
            registry.require("example", "read_job")
        self.assertEqual(error.exception.reason, "capability_not_verified")

    def test_login_state_is_distinct_from_unsupported(self):
        class Detail:
            def read_job(self, ref):
                return make_record()

        registry = self.module.SourceRegistry()
        self.register(registry, state="auth_required", read_job=Detail())
        with self.assertRaises(self.module.SourceError) as error:
            registry.require("example", "read_job")
        self.assertEqual(error.exception.reason, "auth_required")

    def test_new_source_keys_need_no_platform_enumeration(self):
        class Detail:
            def read_job(self, ref):
                return make_record()

        registry = self.module.SourceRegistry()
        for key in ("custom-employer-a", "mailbox-tenant-b"):
            self.register(registry, key=key, read_job=Detail())
        self.assertEqual(len(registry.for_capability("read_job")), 2)

    def test_no_submit_port_or_lying_implementation_allowed(self):
        registry = self.module.SourceRegistry()
        with self.assertRaises(ValueError):
            self.register(registry, submit_application=object())
        with self.assertRaises(ValueError):
            self.register(registry, read_job=object())

    def test_evidence_and_enablement_are_independent_per_capability(self):
        class Ports:
            def read_job(self, ref):
                return make_record()

            def search_jobs(self, query, cursor=None):
                return []

        registry = self.module.SourceRegistry()
        evidence = Capability(
            CapabilityStatus.VERIFIED, "Fixture", evidence_ref="fixture://source"
        )
        descriptor = self.module.SourceDescriptor(
            key="mixed",
            display_name="Mixed",
            adapter_version="1",
            enabled=True,
            connection_state="ready",
            capabilities={
                "read_job": self.module.RegisteredCapability(evidence, stage="product"),
                "search_jobs": self.module.RegisteredCapability(
                    evidence, stage="local_script"
                ),
            },
        )
        registry.register(descriptor, read_job=Ports(), search_jobs=Ports())
        self.assertIsNotNone(registry.require("mixed", "read_job"))
        with self.assertRaises(self.module.SourceError) as error:
            registry.require("mixed", "search_jobs")
        self.assertEqual(error.exception.reason, "capability_not_verified")
        self.assertEqual(registry.for_capability("search_jobs"), [])

    def test_disabled_source_and_duplicate_install_are_explicit(self):
        class Detail:
            def read_job(self, ref):
                return make_record()

        registry = self.module.SourceRegistry()
        self.register(registry, enabled=False, read_job=Detail())
        with self.assertRaises(self.module.SourceError) as error:
            registry.require("example", "read_job")
        self.assertEqual(error.exception.reason, "disabled")
        with self.assertRaises(ValueError):
            self.register(registry, read_job=Detail())


if __name__ == "__main__":
    unittest.main()
