"""`klean project-create`: a Python or C# project folder in the LEAN CLI's layout, with the KRX
models next to the algorithm."""

from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

from klean.workspace import REPO_ROOT, KleanError, Workspace

PY_MODELS = REPO_ROOT / "examples" / "python" / "krx_models.py"
CS_MODELS = REPO_ROOT / "examples" / "KrxModels.cs"

PY_TEMPLATE = '''# region imports
from AlgorithmImports import *
from krx_models import KrxBoards, krx_benchmark, krx_initialize
# endregion


class {cls}(QCAlgorithm):
    """KRX strategy template (klean): buy and hold Samsung Electronics with KRX fees and taxes."""

    def initialize(self):
        self.set_time_zone("Asia/Seoul")
        self.set_account_currency("KRW")
        self.set_start_date(2024, 1, 2)
        self.set_cash(100_000_000)
        boards = KrxBoards.load()
        self.set_security_initializer(lambda security: krx_initialize(security, boards))
        self.set_benchmark(krx_benchmark("kospi200"))
        self.samsung = self.add_equity("005930", Resolution.DAILY, Market.KRX).symbol

    def on_data(self, data: Slice):
        if not self.portfolio.invested:
            self.set_holdings(self.samsung, 0.9)
'''

CS_TEMPLATE = '''using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{{
    /// <summary>KRX strategy template (klean): buy and hold Samsung Electronics with KRX fees and taxes.</summary>
    public class {cls} : QCAlgorithm
    {{
        private Symbol _samsung;

        public override void Initialize()
        {{
            SetTimeZone("Asia/Seoul");
            SetAccountCurrency("KRW");
            SetStartDate(2024, 1, 2);
            SetCash(100_000_000);
            var boards = KrxBoards.Load();
            SetSecurityInitializer(security =>
            {{
                security.SetFeeModel(new KrxFeeModel(boards));
                security.PriceVariationModel = new KrxPriceVariationModel(boards);
            }});
            SetBenchmark(KrxIndex.Benchmark("kospi200"));
            _samsung = AddEquity("005930", Resolution.Daily, Market.KRX).Symbol;
        }}

        public override void OnData(Slice slice)
        {{
            if (!Portfolio.Invested) SetHoldings(_samsung, 0.9m);
        }}
    }}
}}
'''

# References the DLLs of the LEAN build named in klean.json; Private=false so nothing is copied
# (the launcher already has them loaded). Same target framework as LEAN at the tested commit.
CSPROJ_TEMPLATE = '''<Project Sdk="Microsoft.NET.Sdk">
  <!-- klean C# project: compiled against the LEAN build in klean.json (lean_root). -->
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <OutputType>Library</OutputType>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <NoWarn>CS0618;CS1591</NoWarn>
    <LeanBin Condition="'$(LeanBin)' == ''">{lean_bin}</LeanBin>
  </PropertyGroup>
  <ItemGroup>
    <Compile Remove="backtests/**" />
    <!-- LEAN's own example algorithms are not a dependency of a user project -->
    <Reference Include="$(LeanBin)/QuantConnect.*.dll" Exclude="$(LeanBin)/QuantConnect.Algorithm.CSharp.dll" Private="false" />
    <Reference Include="$(LeanBin)/NodaTime.dll" Private="false" />
    <Reference Include="$(LeanBin)/Newtonsoft.Json.dll" Private="false" />
    <Reference Include="$(LeanBin)/Python.Runtime.dll" Private="false" />
  </ItemGroup>
</Project>
'''


def class_name(name: str) -> str:
    """'KRX Top 20' -> 'KRXTop20'; must be a valid Python/C# identifier."""
    parts = re.findall(r"[A-Za-z0-9]+", name)
    cls = "".join(p[:1].upper() + p[1:] for p in parts) or "KrxAlgorithm"
    return cls if not cls[0].isdigit() else "Krx" + cls


def create(ws: Workspace, name: str, language: str) -> Path:
    project = ws.root / name
    if project.exists():
        raise KleanError(f"{project} already exists")
    cls = class_name(Path(name).name)
    project.mkdir(parents=True)
    if language == "python":
        (project / "main.py").write_text(PY_TEMPLATE.format(cls=cls), encoding="utf-8")
        shutil.copy(PY_MODELS, project / "krx_models.py")
    elif language == "csharp":
        (project / "Main.cs").write_text(CS_TEMPLATE.format(cls=cls), encoding="utf-8")
        shutil.copy(CS_MODELS, project / "KrxModels.cs")
        (project / f"{cls}.csproj").write_text(CSPROJ_TEMPLATE.format(lean_bin=ws.launcher_dir), encoding="utf-8")
    else:
        raise KleanError(f"unknown language {language!r} (python or csharp)")
    return project


def language_of(project: Path) -> str:
    if list(project.glob("*.csproj")):
        return "csharp"
    if (project / "main.py").exists():
        return "python"
    raise KleanError(f"{project} has neither main.py nor a .csproj")


def python_algorithm_class(main_py: Path) -> str:
    """Name of the QCAlgorithm subclass in main.py."""
    tree = ast.parse(main_py.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if (isinstance(base, ast.Name) and base.id == "QCAlgorithm") or \
                        (isinstance(base, ast.Attribute) and base.attr == "QCAlgorithm"):
                    return node.name
    raise KleanError(f"no class deriving from QCAlgorithm in {main_py}")


def csharp_algorithm_class(project: Path) -> str:
    pattern = re.compile(r"class\s+(\w+)\s*:\s*QCAlgorithm\b")
    found = []
    for path in sorted(project.rglob("*.cs")):
        if "backtests" in path.parts or "obj" in path.parts or "bin" in path.parts:
            continue
        found += pattern.findall(path.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise KleanError(f"expected one class deriving from QCAlgorithm in {project}, found {found or 'none'}")
    return found[0]
