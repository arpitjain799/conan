import os
import platform
import shutil
import textwrap

import pytest

from conans.test.assets.cmake import gen_cmakelists
from conans.test.assets.genconanfile import GenConanfile
from conans.test.assets.sources import gen_function_cpp
from conans.test.utils.test_files import temp_folder
from conans.test.utils.tools import TestClient
from conans.util.files import save


@pytest.fixture(scope="module")
def _client():
    c = TestClient()
    c.run("new cmake_lib -d name=hello -d version=0.1")
    c.run("create . -o *:shared=True -tf=")
    conanfile = textwrap.dedent("""
           import os
           from conan import ConanFile
           from conan.tools.files import save
           class Tool(ConanFile):
               name = "tool"
               version = "1.0"
               def package(self):
                   save(self, os.path.join(self.package_folder, "build", "my_tools.cmake"),
                        'set(MY_TOOL_VARIABLE "Hello world!")')

               def package_info(self):
                   self.cpp_info.includedirs = []
                   self.cpp_info.libdirs = []
                   self.cpp_info.bindirs = []
                   path_build_modules = os.path.join("build", "my_tools.cmake")
                   self.cpp_info.set_property("cmake_build_modules", [path_build_modules])
               """)
    c.save({"conanfile.py": conanfile}, clean_first=True)
    c.run("create .")
    return c


@pytest.fixture()
def client(_client):
    """ this is much faster than creating and uploading everythin
    """
    client = TestClient(default_server_user=True)
    shutil.rmtree(client.cache_folder)
    shutil.copytree(_client.cache_folder, client.cache_folder)
    return client


@pytest.mark.tool("cmake")
def test_install_deploy(client):
    c = client
    custom_content = 'message(STATUS "MY_TOOL_VARIABLE=${MY_TOOL_VARIABLE}!")'
    cmake = gen_cmakelists(appname="my_app", appsources=["main.cpp"], find_package=["hello", "tool"],
                           custom_content=custom_content)
    deploy = textwrap.dedent("""
        import os, shutil

        # USE **KWARGS to be robust against changes
        def deploy(graph, output_folder, **kwargs):
            conanfile = graph.root.conanfile
            for r, d in conanfile.dependencies.items():
                new_folder = os.path.join(output_folder, d.ref.name)
                shutil.copytree(d.package_folder, new_folder)
                d.set_deploy_folder(new_folder)
        """)
    c.save({"conanfile.txt": "[requires]\nhello/0.1\ntool/1.0",
            "deploy.py": deploy,
            "CMakeLists.txt": cmake,
            "main.cpp": gen_function_cpp(name="main", includes=["hello"], calls=["hello"])},
           clean_first=True)
    c.run("install . -o *:shared=True "
          "--deploy=deploy.py -of=mydeploy -g CMakeToolchain -g CMakeDeps")
    c.run("remove * -c")  # Make sure the cache is clean, no deps there
    arch = c.get_default_host_profile().settings['arch']
    deps = c.load(f"mydeploy/hello-release-{arch}-data.cmake")
    assert 'set(hello_PACKAGE_FOLDER_RELEASE "${CMAKE_CURRENT_LIST_DIR}/hello")' in deps
    assert 'set(hello_INCLUDE_DIRS_RELEASE "${hello_PACKAGE_FOLDER_RELEASE}/include")' in deps
    assert 'set(hello_LIB_DIRS_RELEASE "${hello_PACKAGE_FOLDER_RELEASE}/lib")' in deps

    # We can fully move it to another folder, and still works
    tmp = os.path.join(temp_folder(), "relocated")
    shutil.copytree(c.current_folder, tmp)
    shutil.rmtree(c.current_folder)
    c2 = TestClient(current_folder=tmp)
    # I can totally build without errors with deployed
    c2.run_command("cmake . -DCMAKE_TOOLCHAIN_FILE=mydeploy/conan_toolchain.cmake "
                   "-DCMAKE_BUILD_TYPE=Release")
    assert "MY_TOOL_VARIABLE=Hello world!!" in c2.out
    c2.run_command("cmake --build . --config Release")
    if platform.system() == "Windows":  # Only the .bat env-generators are relocatable
        cmd = r"mydeploy\conanrun.bat && Release\my_app.exe"
        # For Lunux: cmd = ". mydeploy/conanrun.sh && ./my_app"
        c2.run_command(cmd)
        assert "hello/0.1: Hello World Release!" in c2.out


@pytest.mark.tool("cmake")
def test_install_full_deploy_layout(client):
    c = client
    custom_content = 'message(STATUS "MY_TOOL_VARIABLE=${MY_TOOL_VARIABLE}!")'
    cmake = gen_cmakelists(appname="my_app", appsources=["main.cpp"], find_package=["hello", "tool"],
                           custom_content=custom_content)
    conanfile = textwrap.dedent("""
        [requires]
        hello/0.1
        tool/1.0
        [generators]
        CMakeDeps
        CMakeToolchain
        [layout]
        cmake_layout
        """)
    c.save({"conanfile.txt": conanfile,
            "CMakeLists.txt": cmake,
            "main.cpp": gen_function_cpp(name="main", includes=["hello"], calls=["hello"])},
           clean_first=True)
    c.run("install . -o *:shared=True --deploy=full_deploy.py")
    c.run("remove * -c")  # Make sure the cache is clean, no deps there
    arch = c.get_default_host_profile().settings['arch']
    folder = "/Release" if platform.system() != "Windows" else ""
    rel_path = "../../" if platform.system() == "Windows" else "../../../"
    deps = c.load(f"build{folder}/generators/hello-release-{arch}-data.cmake")
    assert 'set(hello_PACKAGE_FOLDER_RELEASE "${CMAKE_CURRENT_LIST_DIR}/' \
           f'{rel_path}full_deploy/host/hello/0.1/Release/{arch}")' in deps
    assert 'set(hello_INCLUDE_DIRS_RELEASE "${hello_PACKAGE_FOLDER_RELEASE}/include")' in deps
    assert 'set(hello_LIB_DIRS_RELEASE "${hello_PACKAGE_FOLDER_RELEASE}/lib")' in deps

    # We can fully move it to another folder, and still works
    tmp = os.path.join(temp_folder(), "relocated")
    shutil.copytree(c.current_folder, tmp)
    shutil.rmtree(c.current_folder)
    c2 = TestClient(current_folder=tmp)
    with c2.chdir(f"build{folder}"):
        # I can totally build without errors with deployed
        cmakelist = "../.." if platform.system() != "Windows" else ".."
        c2.run_command(f"cmake {cmakelist} -DCMAKE_TOOLCHAIN_FILE=generators/conan_toolchain.cmake "
                       "-DCMAKE_BUILD_TYPE=Release")
        assert "MY_TOOL_VARIABLE=Hello world!!" in c2.out
        c2.run_command("cmake --build . --config Release")
        if platform.system() == "Windows":  # Only the .bat env-generators are relocatable atm
            cmd = r"generators\conanrun.bat && Release\my_app.exe"
            # For Lunux: cmd = ". mydeploy/conanrun.sh && ./my_app"
            c2.run_command(cmd)
            assert "hello/0.1: Hello World Release!" in c2.out


def test_copy_files_deploy():
    c = TestClient()
    deploy = textwrap.dedent("""
        import os, shutil

        def deploy(graph, output_folder, **kwargs):
            conanfile = graph.root.conanfile
            for r, d in conanfile.dependencies.items():
                bindir = os.path.join(d.package_folder, "bin")
                for f in os.listdir(bindir):
                    shutil.copy2(os.path.join(bindir, f), os.path.join(output_folder, f))
        """)
    c.save({"conanfile.txt": "[requires]\nhello/0.1",
            "deploy.py": deploy,
            "hello/conanfile.py": GenConanfile("hello", "0.1").with_package_file("bin/file.txt",
                                                                                 "content!!")})
    c.run("create hello")
    c.run("install . --deploy=deploy.py -of=mydeploy")


def test_multi_deploy():
    """ check that we can add more than 1 deployer in the command line, both in local folders
    and in cache.
    Also testing that using .py extension or not, is the same
    Also, the local folder have precedence over the cache extensions
    """
    c = TestClient()
    deploy1 = textwrap.dedent("""
        def deploy(graph, output_folder, **kwargs):
            conanfile = graph.root.conanfile
            conanfile.output.info("deploy1!!")
        """)
    deploy2 = textwrap.dedent("""
        def deploy(graph, output_folder, **kwargs):
            conanfile = graph.root.conanfile
            conanfile.output.info("sub/deploy2!!")
        """)
    deploy_cache = textwrap.dedent("""
        def deploy(graph, output_folder, **kwargs):
            conanfile = graph.root.conanfile
            conanfile.output.info("deploy cache!!")
        """)
    save(os.path.join(c.cache_folder, "extensions", "deploy", "deploy_cache.py"), deploy_cache)
    # This should never be called in this test, always the local is found first
    save(os.path.join(c.cache_folder, "extensions", "deploy", "mydeploy.py"), "CRASH!!!!")
    c.save({"conanfile.txt": "",
            "mydeploy.py": deploy1,
            "sub/mydeploy2.py": deploy2})

    c.run("install . --deploy=mydeploy --deploy=sub/mydeploy2 --deploy=deploy_cache")
    assert "conanfile.txt: deploy1!!" in c.out
    assert "conanfile.txt: sub/deploy2!!" in c.out
    assert "conanfile.txt: deploy cache!!" in c.out

    # Now with .py extension
    c.run("install . --deploy=mydeploy.py --deploy=sub/mydeploy2.py --deploy=deploy_cache.py")
    assert "conanfile.txt: deploy1!!" in c.out
    assert "conanfile.txt: sub/deploy2!!" in c.out
    assert "conanfile.txt: deploy cache!!" in c.out


def test_builtin_full_deploy():
    """ check the built-in full_deploy
    """
    c = TestClient()
    conanfile = textwrap.dedent("""
        import os
        from conan import ConanFile
        from conan.tools.files import save
        class Pkg(ConanFile):
            settings = "arch", "build_type"
            def package(self):
                content = f"{self.settings.build_type}-{self.settings.arch}"
                save(self, os.path.join(self.package_folder, "include/hello.h"), content)

            def package_info(self):
                path_build_modules = os.path.join("build", "my_tools_{}.cmake".format(self.context))
                self.cpp_info.set_property("cmake_build_modules", [path_build_modules])
            """)
    c.save({"conanfile.py": conanfile})
    c.run("create . --name=dep --version=0.1")
    c.run("create . --name=dep --version=0.1 -s build_type=Debug -s arch=x86")
    c.save({"conanfile.txt": "[requires]\ndep/0.1"}, clean_first=True)
    c.run("install . --deploy=full_deploy -of=output -g CMakeDeps")
    assert "Conan built-in full deployer" in c.out
    c.run("install . --deploy=full_deploy -of=output -g CMakeDeps "
          "-s build_type=Debug -s arch=x86")

    host_arch = c.get_default_host_profile().settings['arch']
    release = c.load(f"output/full_deploy/host/dep/0.1/Release/{host_arch}/include/hello.h")
    assert f"Release-{host_arch}" in release
    debug = c.load("output/full_deploy/host/dep/0.1/Debug/x86/include/hello.h")
    assert "Debug-x86" in debug
    cmake_release = c.load(f"output/dep-release-{host_arch}-data.cmake")
    assert 'set(dep_INCLUDE_DIRS_RELEASE "${dep_PACKAGE_FOLDER_RELEASE}/include")' in cmake_release
    assert f"${{CMAKE_CURRENT_LIST_DIR}}/full_deploy/host/dep/0.1/Release/{host_arch}" in cmake_release
    assert 'set(dep_BUILD_MODULES_PATHS_RELEASE ' \
           '"${dep_PACKAGE_FOLDER_RELEASE}/build/my_tools_host.cmake")' in cmake_release
    cmake_debug = c.load("output/dep-debug-x86-data.cmake")
    assert 'set(dep_INCLUDE_DIRS_DEBUG "${dep_PACKAGE_FOLDER_DEBUG}/include")' in cmake_debug
    assert "${CMAKE_CURRENT_LIST_DIR}/full_deploy/host/dep/0.1/Debug/x86" in cmake_debug
    assert 'set(dep_BUILD_MODULES_PATHS_DEBUG ' \
           '"${dep_PACKAGE_FOLDER_DEBUG}/build/my_tools_host.cmake")' in cmake_debug


def test_deploy_reference():
    """ check that we can also deploy a reference
    """
    c = TestClient()
    c.save({"conanfile.py": GenConanfile("pkg", "1.0").with_package_file("include/hi.h", "hi")})
    c.run("create .")

    c.run("install  --requires=pkg/1.0 --deploy=full_deploy --output-folder=output")
    # NOTE: Full deployer always use build_type/arch, even if None/None in the path, same structure
    header = c.load("output/full_deploy/host/pkg/1.0/include/hi.h")
    assert "hi" in header

    # Testing that we can deploy to the current folder too
    c.save({}, clean_first=True)
    c.run("install  --requires=pkg/1.0 --deploy=full_deploy")
    # NOTE: Full deployer always use build_type/arch, even if None/None in the path, same structure
    header = c.load("full_deploy/host/pkg/1.0/include/hi.h")
    assert "hi" in header


def test_deploy_overwrite():
    """ calling several times the install --deploy doesn't crash if files already exist
    """
    c = TestClient()
    c.save({"conanfile.py": GenConanfile("pkg", "1.0").with_package_file("include/hi.h", "hi")})
    c.run("create .")

    c.run("install  --requires=pkg/1.0 --deploy=full_deploy --output-folder=output")
    header = c.load("output/full_deploy/host/pkg/1.0/include/hi.h")
    assert "hi" in header

    # modify the package
    c.save({"conanfile.py": GenConanfile("pkg", "1.0").with_package_file("include/hi.h", "bye")})
    c.run("create .")
    c.run("install  --requires=pkg/1.0 --deploy=full_deploy --output-folder=output")
    header = c.load("output/full_deploy/host/pkg/1.0/include/hi.h")
    assert "bye" in header


def test_deploy_editable():
    """ when deploying something that is editable, with the full_deploy built-in, it will copy the
    editable files as-is, but it doesn't fail at this moment
    """

    c = TestClient()
    c.save({"conanfile.py": GenConanfile("pkg", "1.0"),
            "src/include/hi.h": "hi"})
    c.run("editable add .")

    # If we don't change to another folder, the full_deploy will be recursive and fail
    with c.chdir(temp_folder()):
        c.run("install  --requires=pkg/1.0 --deploy=full_deploy --output-folder=output")
        header = c.load("output/full_deploy/host/pkg/1.0/src/include/hi.h")
        assert "hi" in header


def test_deploy_single_package():
    """ Let's try a deploy that executes on a single package reference
    """
    c = TestClient()
    c.save({"conanfile.py": GenConanfile("pkg", "1.0").with_package_file("include/hi.h", "hi"),
            "consumer/conanfile.txt": "[requires]\npkg/1.0"})
    c.run("create .")

    # if we deploy one --requires, we get that package
    c.run("install  --requires=pkg/1.0 --deploy=direct_deploy --output-folder=output")
    header = c.load("output/direct_deploy/pkg/include/hi.h")
    assert "hi" in header

    # If we deploy a local conanfile.txt, we get deployed its direct dependencies
    c.run("install consumer/conanfile.txt --deploy=direct_deploy --output-folder=output2")
    header = c.load("output2/direct_deploy/pkg/include/hi.h")
    assert "hi" in header
