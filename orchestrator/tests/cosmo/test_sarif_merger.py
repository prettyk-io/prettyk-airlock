import sys, json, tempfile, shutil
from pathlib import Path
import pytest

sys.path.insert(0, r'D:\cosmoport2\orchestrator')
from orchestrator.cosmo.ledger.sarif_merger import StreamingSarifMerger, make_shard_sarif, _validate_sarif
from orchestrator.cosmo.ledger.artifact_store import ArtifactStore


@pytest.fixture
def store():
    d = tempfile.mkdtemp(prefix='sm_')
    s = ArtifactStore(base_dir=d)
    yield s
    shutil.rmtree(d, ignore_errors=True)


def r(rid, sev, uri, idx):
    return {'ruleId': rid, 'level': sev, 'kind': 'fail',
            'message': {'text': f'F{idx}'},
            'locations': [{'physicalLocation': {
                'artifactLocation': {'uri': uri},
                'region': {'startLine': idx + 1}}}]}


def rule(id, name, sev):
    return {'id': id, 'name': name, 'shortDescription': {'text': name},
            'properties': {'severity': sev}}


def w(store, path, doc):
    p = Path(store._base) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding='utf-8')


class Test50Shards:
    def test_50_merge(self, store):
        tot = 0
        for i in range(50):
            rid = f'R{(i % 10):03d}'
            fps = (i % 5) + 1
            tot += fps
            fings = [r(rid, ['error','warning','note'][j%3], f'src/m-{i}/f-{j}.py', j) for j in range(fps)]
            rls = [rule(rid, f'Rule{rid}', ['Critical','High','Medium'][i%3])]
            sh = make_shard_sarif(fings, rls)
            sh['runs'][0]['properties'] = {'total_findings': fps}
            w(store, f's/s-{i:03d}.json', sh)

        m = StreamingSarifMerger(store)
        result = m.merge_sarif_streams([f's/s-{i:03d}.json' for i in range(50)], 'm/fifty.sarif')

        run = result['runs'][0]
        assert len(run['results']) == tot
        assert len(run['tool']['driver']['rules']) == 10
        p = run.get('properties', {})
        assert p['shard_count'] == 50
        assert p['unique_rules'] == 10

        # validate output
        _validate_sarif(result)
        out = Path(store._base) / 'm/fifty.sarif'
        assert out.exists()
        parsed = json.loads(out.read_text(encoding='utf-8'))
        assert parsed['version'] == '2.1.0'

    def test_50_big(self, store):
        for i in range(50):
            rid = f'R{(i % 8):03d}'
            fings = [r(rid, 'note', f'f-{i}-{j}.py', i+j) for j in range(100)]
            w(store, f's/big-{i}.json', make_shard_sarif(fings, [rule(rid, f'R{rid}', 'Medium')]))

        m = StreamingSarifMerger(store)
        result = m.merge_sarif_streams([f's/big-{i}.json' for i in range(50)], 'm/big.sarif')
        assert len(result['runs'][0]['results']) == 5000
        assert len(result['runs'][0]['tool']['driver']['rules']) == 8

    def test_50_all_present(self, store):
        expected = []
        for i in range(50):
            rid = f'R{(i % 10):03d}'
            uri = f'm-{i}/f.py'
            expected.append(f'{rid}|{uri}')
            w(store, f's/u-{i}.json', make_shard_sarif(
                [r(rid, 'note', uri, i)], [rule(rid, 'R', 'High')]))

        m = StreamingSarifMerger(store)
        merged = m.merge_sarif_streams([f's/u-{i}.json' for i in range(50)], 'm/all.sarif')

        actual = []
        for res in merged['runs'][0]['results']:
            uri = res['locations'][0]['physicalLocation']['artifactLocation']['uri']
            actual.append(f"{res['ruleId']}|{uri}")

        assert sorted(actual) == sorted(expected)
        assert len(actual) == 50


class TestDedup:
    def test_dedup(self, store):
        r1 = [rule('R001', 'SQLi', 'High')]
        for i, uri in enumerate(['a.py', 'b.py', 'c.py']):
            w(store, f's/d-{i}.json', make_shard_sarif([r('R001', 'warning', uri, i)], r1))

        m = StreamingSarifMerger(store)
        result = m.merge_sarif_streams([f's/d-{i}.json' for i in range(3)], 'm/dedup.sarif')
        rules = result['runs'][0]['tool']['driver']['rules']
        assert len(rules) == 1
        assert rules[0]['id'] == 'R001'

    def test_severity_max(self, store):
        w(store, 's/med.json', make_shard_sarif(
            [r('R9', 'note', 'med.py', 0)], [rule('R9', 'X', 'Medium')]))
        w(store, 's/crit.json', make_shard_sarif(
            [r('R9', 'error', 'crit.py', 1)], [rule('R9', 'X', 'Critical')]))

        m = StreamingSarifMerger(store)
        result = m.merge_sarif_streams(['s/med.json', 's/crit.json'], 'm/sev.sarif')
        sev = result['runs'][0]['tool']['driver']['rules'][0].get('properties', {}).get('severity', '')
        assert sev == 'Critical'


class TestSmall:
    def test_empty(self, store):
        m = StreamingSarifMerger(store)
        r = m.merge_sarif_streams([], 'm/e.sarif')
        assert r['version'] == '2.1.0'

    def test_single(self, store):
        w(store, 's/a.json', make_shard_sarif([r('R1','error','a.py',0)], [rule('R1','R1','Critical')]))
        m = StreamingSarifMerger(store)
        res = m.merge_sarif_streams(['s/a.json'], 'm/s.sarif')
        assert len(res['runs'][0]['results']) == 1


class TestHelper:
    def test_basic(self):
        d = make_shard_sarif([], [])
        assert d['version'] == '2.1.0'

    def test_with_findings(self):
        d = make_shard_sarif([r('R1','warning','a.py',0)], [rule('R1','R1','Medium')])
        assert len(d['runs'][0]['results']) == 1