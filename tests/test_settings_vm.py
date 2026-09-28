import pytest
from zepp_report.settings import Settings


@pytest.mark.parametrize('key,value', [
    ('VM_QUERY_URL', 'file:///tmp/vm'),
    ('VM_QUERY_URL', 'https://user:password@vm.example'),
    ('VM_QUERY_URL', 'https://vm.example?token=secret'),
    ('VM_QUERY_URL', 'https://vm.example#fragment'),
    ('VM_RETENTION_DAYS', '0'),
    ('VM_RETENTION_DAYS', '36501'),
    ('VM_DEDUP_INTERVAL_SECONDS', '-1'),
    ('VM_DEDUP_INTERVAL_SECONDS', 'nan'),
    ('VM_DEDUP_INTERVAL_SECONDS', 'inf'),
])
def test_reject_invalid_vm_audit_configuration(tmp_path, key, value):
    with pytest.raises(ValueError):
        Settings(tmp_path, {'ADMIN_PASSWORD': 'test-password-long', key: value})


def test_vm_audit_millisecond_configuration_and_secret_redaction(tmp_path):
    settings = Settings(tmp_path, {
        'ADMIN_PASSWORD': 'test-password-long',
        'VM_QUERY_URL': 'https://vm.example/select/0/prometheus/',
        'VM_RETENTION_DAYS': '3650',
        'VM_DEDUP_INTERVAL_SECONDS': '0.001',
        'VM_BEARER_TOKEN': 'private-token',
    })
    assert settings.vm_query_url == 'https://vm.example/select/0/prometheus'
    assert settings.vm_retention_days == 3650
    assert settings.vm_dedup_seconds == .001
    assert 'private-token' not in str(settings.public())
