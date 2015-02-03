from __future__ import absolute_import, division, print_function

try:
    from pywebhdfs.webhdfs import PyWebHdfsClient
except ImportError:
    import pytest
    pytest.importorskip('does_not_exist')

import uuid
from into.backends.hdfs import (discover, HDFS, CSV, TableProxy, SSH)
from into.backends.sql import resource
from into import into, drop, JSONLines
from into.utils import filetext, ignoring
import sqlalchemy as sa
from datashape import dshape
from into.directory import Directory
from contextlib import contextmanager
import os

host = '' or os.environ.get('HDFS_TEST_HOST')

if not host:
    import pytest
    pytest.importorskip('does_not_exist')


hdfs = PyWebHdfsClient(host=host, port='14000', user_name='hdfs')
hdfs_csv= HDFS(CSV)('/user/hive/mrocklin/accounts/accounts.csv', hdfs=hdfs)
hdfs_directory = HDFS(Directory(CSV))('/user/hive/mrocklin/accounts/', hdfs=hdfs)
ds = dshape('var * {id: ?int64, name: ?string, amount: ?int64}')
engine = resource('hive://hdfs@%s:10000/default' % host)


def test_discover():
    assert str(discover(hdfs_csv)).replace('?', '') == \
            'var * {id: int64, name: string, amount: int64}'

def test_discover_hdfs_directory():
    assert str(discover(hdfs_directory)).replace('?', '') == \
            'var * {id: int64, name: string, amount: int64}'


def normalize(s):
    return ' '.join(s.split())


auth = {'hostname': host,
        'key_filename': os.path.expanduser('~/.ssh/cdh_testing.key'),
        'username': 'ubuntu'}

ssh_csv= SSH(CSV)('/home/ubuntu/into-testing/accounts1.csv', **auth)
ssh_directory = SSH(Directory(CSV))('/home/ubuntu/into-testing/', **auth)


@contextmanager
def hive_table(host):
    name = ('temp' + str(uuid.uuid1()).replace('-', ''))[:30]
    uri = 'hive://hdfs@%s:10000/default::%s' % (host, name)

    try:
        yield uri
    finally:
        with ignoring(Exception):
            drop(uri)


def test_hdfs_hive_creation():
    with hive_table(host) as uri:
        t = into(uri, hdfs_directory)
        assert isinstance(t, sa.Table)
        assert len(into(list, t)) > 0
        assert discover(t) == ds


def test_ssh_hive_creation():
    with hive_table(host) as uri:
        t = into(uri, ssh_csv)
        assert isinstance(t, sa.Table)
        assert len(into(list, t)) > 0


def test_ssh_directory_hive_creation():
    with hive_table(host) as uri:
        t = into(uri, ssh_directory)
        assert isinstance(t, sa.Table)
        assert discover(t) == ds
        assert len(into(list, t)) > 0


def test_ssh_hive_creation_with_full_urls():
    with hive_table(host) as uri:
        t = into(uri, 'ssh://ubuntu@%s:accounts.csv' % host,
                 key_filename=os.path.expanduser('~/.ssh/cdh_testing.key'))
        assert isinstance(t, sa.Table)
        n = len(into(list, t))
        assert n > 0

        # Load it again
        into(t, 'ssh://ubuntu@%s:accounts.csv' % host,
             key_filename=os.path.expanduser('~/.ssh/cdh_testing.key'))

        # Doubles length
        assert len(into(list, t)) == 2 * n


def test_hive_resource():
    db = resource('hive://hdfs@%s:10000/default' % host)
    assert isinstance(db, sa.engine.Engine)

    db = resource('hive://%s/' % host)
    assert isinstance(db, sa.engine.Engine)
    assert str(db.url) == 'hive://hdfs@%s:10000/default' % host


def test_hdfs_resource():
    r = resource('hdfs://user@hostname:1234:/path/to/myfile.json')
    assert isinstance(r, HDFS(JSONLines))
    assert r.hdfs.user_name == 'user'
    assert r.hdfs.host == 'hostname'
    assert r.hdfs.port == '1234'
    assert r.path == '/path/to/myfile.json'

    assert isinstance(resource('hdfs://path/to/myfile.csv',
                                host='host', user='user', port=1234),
                      HDFS(CSV))
    assert isinstance(resource('hdfs://path/to/*.csv',
                                host='host', user='user', port=1234),
                      HDFS(Directory(CSV)))


@contextmanager
def tmpfile_hdfs(ext=''):
    fn = str(uuid.uuid1())
    if ext:
        fn = fn + '.' + ext

    try:
        yield fn
    finally:
        hdfs.delete_file_dir(fn)


def test_copy_local_files_to_hdfs():
    with tmpfile_hdfs() as target:
        with filetext('name,amount\nAlice,100\nBob,200') as source:
            csv = CSV(source)
            scsv = HDFS(CSV)(target, hdfs=hdfs)
            into(scsv, csv)

            assert discover(scsv) == discover(csv)
