#
# Copyright (c) 2006, 2007 Canonical
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
#
# This file is part of Storm Object Relational Mapper.
#
# Storm is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation; either version 2.1 of
# the License, or (at your option) any later version.
#
# Storm is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from builtins import str
from builtins import object
import traceback
import sys
import os

from storm.locals import StormError, Store, create_database
from storm.schema.patch import (
    Patch, PatchApplier, UnknownPatchError, BadPatchError, PatchSet)
from tests.mocker import MockerTestCase


patch_test_0 = """
x = None
def apply(store):
    global x
    x = 42
    from mypackage import shared_data
    shared_data.append(42)
"""

patch_test_1 = """
y = None
def apply(store):
    global y
    y = 380
    from mypackage import shared_data
    shared_data.append(380)
"""

patch_explosion = """
from storm.locals import StormError

def apply(store):
    raise StormError('KABOOM!')
"""

patch_after_explosion = """
def apply(store):
    pass
"""

patch_no_args_apply = """
def apply():
    pass
"""

patch_missing_apply = """
def misnamed_apply(store):
    pass
"""

patch_name_error = """
def apply(store):
    blah # Comment
"""


class MockPatchStore(object):

    def __init__(self, database, patches=[]):
        self.database = database
        self.rolled_back = 0
        self.committed = 0
        self.patches = patches
        self.objs = []

    def execute(self, statement, params=None, noresult=False):
        pass

    def find(self, cls_spec, *args, **kwargs):
        return self.patches

    def rollback(self):
        self.rolled_back += 1

    def add(self, obj):
        self.objs.append(obj)

    def commit(self):
        self.committed += 1


class PatchApplierTest(MockerTestCase):

    def setUp(self):
        super(PatchApplierTest, self).setUp()

        self.patchdir = self.makeDir()
        self.pkgdir = os.path.join(self.patchdir, "mypackage")
        os.makedirs(self.pkgdir)

        f = open(os.path.join(self.pkgdir, "__init__.py"), "w")
        f.write("shared_data = []")
        f.close()

        # Order of creation here is important to try to screw up the
        # patch ordering, as os.listdir returns in order of mtime (or
        # something).
        for pname, data in [("patch_380.py", patch_test_1),
                            ("patch_42.py", patch_test_0)]:
            self.add_module(pname, data)

        sys.path.append(self.patchdir)

        self.filename = self.makeFile()
        self.uri = "sqlite:///%s" % self.filename
        self.store = Store(create_database(self.uri))

        self.store.execute("CREATE TABLE patch "
                           "(version INTEGER NOT NULL PRIMARY KEY)")

        self.assertFalse(self.store.get(Patch, (42)))
        self.assertFalse(self.store.get(Patch, (380)))

        import mypackage
        self.mypackage = mypackage
        self.patch_set = PatchSet(mypackage)

        # Create another connection just to keep track of the state of the
        # whole transaction manager.  See the assertion functions below.
        self.another_store = Store(create_database("sqlite:"))
        self.another_store.execute("CREATE TABLE test (id INT)")
        self.another_store.commit()
        self.prepare_for_transaction_check()

        class Committer(object):

            def commit(committer):
                self.store.commit()
                self.another_store.commit()

            def rollback(committer):
                self.store.rollback()
                self.another_store.rollback()

        self.committer = Committer()
        self.patch_applier = PatchApplier(self.store, self.patch_set,
                                          self.committer)

    def tearDown(self):
        super(PatchApplierTest, self).tearDown()
        self.committer.rollback()
        sys.path.remove(self.patchdir)
        for name in list(sys.modules):
            if name == "mypackage" or name.startswith("mypackage."):
                del sys.modules[name]

    def add_module(self, module_filename, contents):
        filename = os.path.join(self.pkgdir, module_filename)
        file = open(filename, "w")
        file.write(contents)
        file.close()

    def remove_all_modules(self):
        for filename in os.listdir(self.pkgdir):
            os.unlink(os.path.join(self.pkgdir, filename))

    def prepare_for_transaction_check(self):
        self.another_store.execute("DELETE FROM test")
        self.another_store.execute("INSERT INTO test VALUES (1)")

    def assert_transaction_committed(self):
        self.another_store.rollback()
        result = self.another_store.execute("SELECT * FROM test").get_one()
        self.assertEquals(result, (1,),
                          "Transaction manager wasn't committed.")

    def assert_transaction_aborted(self):
        self.another_store.commit()
        result = self.another_store.execute("SELECT * FROM test").get_one()
        self.assertEquals(result, None,
                          "Transaction manager wasn't aborted.")

    def test_apply(self):
        """
        L{PatchApplier.apply} executes the patch with the given version.
        """
        self.patch_applier.apply(42)

        x = getattr(self.mypackage, "patch_42").x
        self.assertEquals(x, 42)
        self.assertTrue(self.store.get(Patch, (42)))
        self.assertTrue("mypackage.patch_42" in sys.modules)

        self.assert_transaction_committed()

    def test_apply_with_patch_directory(self):
        """
        If the given L{PatchSet} uses sub-level patches, then the
        L{PatchApplier.apply} method will look at the per-patch directory and
        apply the relevant sub-level patch.
        """
        path = os.path.join(self.pkgdir, "patch_99")
        self.makeDir(path=path)
        self.makeFile(content="", path=os.path.join(path, "__init__.py"))
        self.makeFile(content=patch_test_0, path=os.path.join(path, "foo.py"))
        self.patch_set._sub_level = "foo"
        self.add_module("patch_99/foo.py", patch_test_0)
        self.patch_applier.apply(99)
        self.assertTrue(self.store.get(Patch, (99)))

    def test_apply_all(self):
        """
        L{PatchApplier.apply_all} executes all unapplied patches.
        """
        self.patch_applier.apply_all()

        self.assertTrue("mypackage.patch_42" in sys.modules)
        self.assertTrue("mypackage.patch_380" in sys.modules)

        x = getattr(self.mypackage, "patch_42").x
        y = getattr(self.mypackage, "patch_380").y

        self.assertEquals(x, 42)
        self.assertEquals(y, 380)

        self.assert_transaction_committed()

    def test_apply_exploding_patch(self):
        """
        L{PatchApplier.apply} aborts the transaction if the patch fails.
        """
        self.remove_all_modules()
        self.add_module("patch_666.py", patch_explosion)
        self.assertRaises(StormError, self.patch_applier.apply, 666)

        self.assert_transaction_aborted()

    def test_wb_apply_all_exploding_patch(self):
        """
        When a patch explodes the store is rolled back to make sure
        that any changes the patch made to the database are removed.
        Any other patches that have been applied successfully before
        it should not be rolled back.  Any patches pending after the
        exploding patch should remain unapplied.
        """
        self.add_module("patch_666.py", patch_explosion)
        self.add_module("patch_667.py", patch_after_explosion)
        self.assertEquals(list(self.patch_applier.get_unapplied_versions()),
                          [42, 380, 666, 667])
        self.assertRaises(StormError, self.patch_applier.apply_all)
        self.assertEquals(list(self.patch_applier.get_unapplied_versions()),
                          [666, 667])

    def test_mark_applied(self):
        """
        L{PatchApplier.mark} marks a patch has applied by inserting a new row
        in the patch table.
        """
        self.patch_applier.mark_applied(42)

        self.assertFalse("mypackage.patch_42" in sys.modules)
        self.assertFalse("mypackage.patch_380" in sys.modules)

        self.assertTrue(self.store.get(Patch, 42))
        self.assertFalse(self.store.get(Patch, 380))

        self.assert_transaction_committed()

    def test_mark_applied_all(self):
        """
        L{PatchApplier.mark_applied_all} marks all pending patches as applied.
        """
        self.patch_applier.mark_applied_all()

        self.assertFalse("mypackage.patch_42" in sys.modules)
        self.assertFalse("mypackage.patch_380" in sys.modules)

        self.assertTrue(self.store.get(Patch, 42))
        self.assertTrue(self.store.get(Patch, 380))

        self.assert_transaction_committed()

    def test_application_order(self):
        """
        L{PatchApplier.apply_all} applies the patches in increasing version
        order.
        """
        self.patch_applier.apply_all()
        self.assertEquals(self.mypackage.shared_data,
                          [42, 380])

    def test_has_pending_patches(self):
        """
        L{PatchApplier.has_pending_patches} returns C{True} if there are
        patches to be applied, C{False} otherwise.
        """
        self.assertTrue(self.patch_applier.has_pending_patches())
        self.patch_applier.apply_all()
        self.assertFalse(self.patch_applier.has_pending_patches())

    def test_abort_if_unknown_patches(self):
        """
        L{PatchApplier.mark_applied} raises and error if the patch table
        contains patches without a matching file in the patch module.
        """
        self.patch_applier.mark_applied(381)
        self.assertRaises(UnknownPatchError, self.patch_applier.apply_all)

    def test_get_unknown_patch_versions(self):
        """
        L{PatchApplier.get_unknown_patch_versions} returns the versions of all
        unapplied patches.
        """
        patches = [Patch(42), Patch(380), Patch(381)]
        my_store = MockPatchStore("database", patches=patches)
        patch_applier = PatchApplier(my_store, self.mypackage)
        self.assertEqual(set([381]),
                         patch_applier.get_unknown_patch_versions())

    def test_no_unknown_patch_versions(self):
        """
        L{PatchApplier.get_unknown_patch_versions} returns an empty set if
        no patches are unapplied.
        """
        patches = [Patch(42), Patch(380)]
        my_store = MockPatchStore("database", patches=patches)
        patch_applier = PatchApplier(my_store, self.mypackage)
        self.assertEqual(set(), patch_applier.get_unknown_patch_versions())

    def test_patch_with_incorrect_apply(self):
        """
        L{PatchApplier.apply_all} raises an error as soon as one of the patches
        to be applied fails.
        """
        self.add_module("patch_999.py", patch_no_args_apply)
        try:
            self.patch_applier.apply_all()
        except BadPatchError as e:
            self.assertTrue("mypackage/patch_999.py" in str(e))
            self.assertTrue("takes no arguments" in str(e))
            self.assertTrue("TypeError" in str(e))
        else:
            self.fail("BadPatchError not raised")

    def test_patch_with_missing_apply(self):
        """
        L{PatchApplier.apply_all} raises an error if one of the patches to
        to be applied has no 'apply' function defined.
        """
        self.add_module("patch_999.py", patch_missing_apply)
        try:
            self.patch_applier.apply_all()
        except BadPatchError as e:
            self.assertTrue("mypackage/patch_999.py" in str(e))
            self.assertTrue("no attribute" in str(e))
            self.assertTrue("AttributeError" in str(e))
        else:
            self.fail("BadPatchError not raised")

    def test_patch_with_syntax_error(self):
        """
        L{PatchApplier.apply_all} raises an error if one of the patches to
        to be applied contains a syntax error.
        """
        self.add_module("patch_999.py", "that's not python")
        try:
            self.patch_applier.apply_all()
        except BadPatchError as e:
            self.assertTrue(" 999 " in str(e))
            self.assertTrue("SyntaxError" in str(e))
        else:
            self.fail("BadPatchError not raised")

    def test_patch_error_includes_traceback(self):
        """
        The exception raised by L{PatchApplier.apply_all} when a patch fails
        include the relevant traceback from the patch.
        """
        self.add_module("patch_999.py", patch_name_error)
        try:
            self.patch_applier.apply_all()
        except BadPatchError as e:
            self.assertTrue("mypackage/patch_999.py" in str(e))
            self.assertTrue("NameError" in str(e))
            self.assertTrue("blah" in str(e))
            formatted = traceback.format_exc()
            self.assertTrue("# Comment" in formatted)
        else:
            self.fail("BadPatchError not raised")


class PatchSetTest(MockerTestCase):

    def setUp(self):
        super(PatchSetTest, self).setUp()
        self.sys_dir = self.makeDir()
        self.package_dir = os.path.join(self.sys_dir, "mypackage")
        os.makedirs(self.package_dir)

        self.makeFile(
            content="", dirname=self.package_dir, basename="__init__.py")

        sys.path.append(self.sys_dir)
        import mypackage
        self.patch_package = PatchSet(mypackage, sub_level="foo")

    def tearDown(self):
        super(PatchSetTest, self).tearDown()
        for name in list(sys.modules):
            if name == "mypackage" or name.startswith("mypackage."):
                del sys.modules[name]

    def test_get_patch_versions(self):
        """
        The C{get_patch_versions} method returns the available patch versions,
        by looking at directories named like "patch_N".
        """
        patch_1_dir = os.path.join(self.package_dir, "patch_1")
        os.makedirs(patch_1_dir)
        self.assertEqual([1], self.patch_package.get_patch_versions())

    def test_get_patch_versions_ignores_non_patch_directories(self):
        """
        The C{get_patch_versions} method ignores files or directories not
        matching the required name pattern.
        """
        random_dir = os.path.join(self.package_dir, "random")
        os.makedirs(random_dir)
        self.assertEqual([], self.patch_package.get_patch_versions())

    def test_get_patch_module(self):
        """
        The C{get_patch_module} method returns the Python module for the patch
        with the given version.
        """
        patch_1_dir = os.path.join(self.package_dir, "patch_1")
        os.makedirs(patch_1_dir)
        self.makeFile(content="", dirname=patch_1_dir, basename="__init__.py")
        self.makeFile(content="", dirname=patch_1_dir, basename="foo.py")
        patch_module = self.patch_package.get_patch_module(1)
        self.assertEqual("mypackage.patch_1.foo", patch_module.__name__)

    def test_get_patch_module_no_sub_level(self):
        """
        The C{get_patch_module} method returns a dummy patch module if no
        sub-level file exists in the patch directory for the given version.
        """
        patch_1_dir = os.path.join(self.package_dir, "patch_1")
        os.makedirs(patch_1_dir)
        patch_module = self.patch_package.get_patch_module(1)
        store = object()
        self.assertIsNone(patch_module.apply(store))
