# Foam-Agent SOP — i4-pv-uhi 全流程标准作业程序

> 本 SOP 从 sg_uhi_pv/i4-pv-uhi 项目实战提炼(2026-09-05 ~ 09-06),覆盖从 STL 几何到热求解收敛交付的完整链路。所有步骤均经实战验证,附实证数据。适用 Foundation OpenFOAM v13(apt 包),本机 p15-control(8 物理核)。

## 总览

```
STL 几何 → 修复/拼合 → mesh 配置渲染 → 并行网格生成 → 工况独立case → 求解 → 后处理定量 → 台账交付
    G1         G2           M1              M2                S1          S2        P1          R1
```

每阶段产物**必须用户检查通过**才进下一级(阶段门)。

---

## G1. STL 几何体检与修复

### 体检(先诊断后动手)
```bash
# 逐件检查: 闭合性/非流形/针状三角形
source of13-env.sh
for f in geometry/*.stl; do surfaceCheck $f | grep -E "closed|one face|>2 faces|min [0-9]"; done
# 针状扫描(min_edge < 0.35m AND max_edge > 1.0m = 针)
uv run --with numpy python scripts/detect_needles.py  # 或内联
```

### 修复管线(如有针状/非流形)
```bash
surfaceSplitNonManifolds geometry/facade_roof.stl geometry/fixed.stl   # 拆非流形边
# 靶向针塌缩(仅塌缩针状短边, 不做全局容差焊接)
uv run --with trimesh --with numpy --with scipy python scripts/repair_needles.py
```

**铁律**: STL 可以直接操作,不需要回 Rhino。优先用已有轮子(surfaceSplitNonManifolds / PyFoam),不手搓括号解析。

### 拼合(ASCII 命名 solid → snappy regions 独立 patch)
```python
# make_named_assembly.py: 二进制 STL → ASCII 命名 3-solid(facade_roof / parapets_wall / pv)
python3 scripts/make_named_assembly.py
```
**验证**: `grep -c "^solid" geometry/i4_assembly.stl` = 3;三角形总数守恒。

---

## M1. 配置渲染(格式/内容分离)

### 文件架构
```
case_config.yaml          ← 唯一内容源(所有数值)
templates/                ← 格式框架(冻结,不手改)
  thermal/                ← 热阶段模板(由官方案 PyFoam 派生)
render_all.sh             ← 网格阶段渲染
render_thermal.sh [case]  ← 热阶段渲染(工况独立case)
```

### 网格配置关键项
```yaml
SNAPPY_GEOMETRY: |          # 命名拼合件 + BOI 盒子
    building  { type triSurfaceMesh; file "i4_assembly.stl"; }
    gapSlab   { type searchableBox; min ...; max ...; }   # lvl5 = PV缝隙5cm
    panelZone ...                                            # lvl4 = 板区10cm
    courtyard ...                                            # lvl3 = 庭院20cm
SNAPPY_REFINEMENT_SURFACES: |  # regions 语法(分patch独立加密)
    building { level (2 2); regions { facade_roof { (2 2); } pv { (2 2); } } }
SNAPPY_LAYERS: |               # ⚠️ region 化后 patch 名要跟 region 名一致!
    building_facade_roof { nSurfaceLayers 2; }
    building_pv            { nSurfaceLayers 0; }  # PV 板缝不加层
```

### 热模板派生(官方案逐字复制 + PyFoam 机械变换)
```bash
uv run --with PyFoam python scripts/derive_thermal_templates.py
# 结构变换用 PyFoam 树编辑; BC 内容 = deepcopy 官方案已有条目
# 驱动值 → {{占位符}} → config-render 填充
```

**已知 PyFoam 副作用(脚本已内置后处理)**:
- 字符串占位符被加引号 `"{{X}}"` → 去引号
- `internalField`/`value` 丢 `uniform` 关键字 → 补回
- `#includeFunc` 被写成键值对 → 恢复指令行

### 渲染后必验(缺键静默失败!)
```bash
bash render_all.sh && grep -c "regions" system/snappyHexMeshDict
bash render_thermal.sh && uv run --with PyFoam python scripts/pyfoam_validate.py .
```

---

## M2. 并行网格生成(8核 MPI)

```bash
bash mesh-parallel.sh    # blockMesh → surfaceFeatures → decomposePar(scotch) → mpirun snappy → reconstructPar → checkMesh
```

### v13 已知坑(全部已修入脚本)
| 坑 | 解法 |
|---|---|
| `reconstructParMesh` 废弃 | `reconstructPar -constant` |
| apt 无真 scotch(dummy 桩) | ThirdParty-13 自建 scotch+ptscotch; env 链序 scotch→真Pstream→顶层→dummy |
| PRRTE 不转发 FOAM_ETC | mpirun 包裹式: `bash -c 'source env && exec foamRun'` |
| libPstream 与 libptscotchDecomp 同目录冲突 | .libs-mpi 只放 libPstream.so 软链 |
| coded BC 编译需 WM 全家变量 | source 官方 config.sh/functions + settings |
| coded BC 缺 OSspecific include | 模板 `codeOptions` 补 `-I$(LIB_SRC)/OSspecific/POSIX/lnInclude` |

### 网格后处理
```bash
collapseEdges -overwrite -dict system/collapseDict   # 边折叠收尾(30s), 不加 -collapseFaces
```

### 网格验收(checkMesh)
- 硬指标: maxNonOrtho < 75, 无负体积, 体积总量一致
- 形式残留(skew/tets/concave)按 NASA 双判据定性 → 用户豁免裁决

---

## S1. 工况独立 case(用户架构定案)

```
run/thermal-carlos0626/       ← 每个工况一个独立目录
  0/ system/ constant/        ← 独立字典和场
  constant/polyMesh → /绝对路径/polyMesh  ← 符号链接共享网格(⚠️ 必须绝对路径)
```

```bash
mkdir -p run/<工况>/{0,system,constant}
ln -sfn $CASE_ROOT/constant/polyMesh run/<工况>/constant/polyMesh
render_thermal.sh run/<工况>
```

---

## S2. 求解(foamRun fluid 稳态)

### 启动前双门禁
1. **静态门**(毫秒): `uv run --with PyFoam python scripts/pyfoam_validate.py <case>`
2. **构造门**(秒级): `endTime=0` 构造运行,一次暴露全部字典/UDF/FO 错误

**禁止拿多步迭代当试错工具。**

### 正式运行
```bash
cd run/<case> && decomposePar -force
mpirun -np 8 bash -c 'source of13-env.sh && exec foamRun -parallel -solver fluid'
```

### 关键 controlDict 设置
```yaml
writeInterval: 100      # ~70min/存盘, 续跑锚点
purgeWrite: 2           # 只留最近 2 个, 磁盘不膨胀
functions:
    #includeFunc patchAverage(T, patch = building_pv)   # T_pv 逐10步
    #includeFunc cellMax(T)
    #includeFunc residuals(U, p_rgh, h, k, omega)
```

### 收敛判定(NASA 双判据)
- 残差: h/omega 降 ≥3 阶
- **关注量平台**: T_pv 波动 < 0.5% 持续 ≥200 步
- 优雅停跑: **等存盘写完再 kill**(kill 与写入相撞 = 存盘截断 = 弃用)

### PV 能量平衡 UDF(carlos0812 逐字派生)
```cpp
// Newton 迭代解 T_pv:
// εσT⁴ + h(T-T_air) + η(T)·G - α·G - εσT_sky⁴ = 0
// 参数全部 {{占位符}} → case_config.yaml 填代表日实测值
```

---

## P1. 后处理定量

### pyvista(大文件可视化首选)
```bash
uv run --with pyvista --with matplotlib python - << 'EOF'
mesh = pv.read("VTK/xxx_700.vtk")
s = mesh.slice(normal="z", origin=(-7,0,25.10))       # 缝隙切片
p = pv.Plotter(off_screen=True, window_size=(1600,1000))
p.add_mesh(s, scalars="T", cmap="turbo", clim=(303,337))
p.screenshot("renders/slice_T.png")
# 定量统计
inpv = (cent[:,0]>-46.2)&...; print(f"PV区缝隙: {T[inpv].mean():.2f}K")
EOF
```

**注意**: pvbatch 对 >400MB 多块 legacy VTK 渲染空白(小文件正常),大文件一律走 pyvista。

---

## R1. 台账交付

```bash
exp run register --project sg_uhi_pv --type simulation --skill foamRun-fluid-<工况> ...
exp run qc-pass --id <run_id>
# 记忆宫殿 palace_runtime.upsert_memory
```

### 交付物
| 物 | 路径 |
|---|---|
| 收敛场 | `run/<case>/<latest_time>/` |
| VTK 检查 | `run/<case>/VTK/*.vtk` |
| 渲染图 | `run/<case>/VTK/renders/*.png` |
| 监控曲线 | `postProcessing/` |
| 台账 | ExperimentOS run + palace memory |

---

## 附录 A: 环境启动

```bash
source of13-env.sh
# 最小激活(绕 bashrc 的 ParaView 探测挂死): scotch→真Pstream→顶层→dummy 链序
# + WM 全家变量(coded BC) + HWLOC_COMPONENTS=-gl(ParaView/串行MPI防卡死)
```

## 附录 B: 已修 bug 清单

| 层 | Bug | 修复 |
|---|---|---|
| env | `source bashrc` 挂死(pvdataserver 探测) | 最小 env 脚本 |
| env | ParaView/串行MPI 启动卡死(hwloc_gl 连 X1 僵死口) | `HWLOC_COMPONENTS=-gl` 入 /usr/bin/paraview 包装器 |
| v13 | eMesh 按文件名生成 | dict 引用跟文件名不跟条目名 |
| v13 | fluid 模块要求 p+p_rgh 并存 | 官方案同时有两个文件 |
| v13 | `surfaceFieldValue` FO 不存在 | 用 `#includeFunc patchAverage/cellMax` |
| 渲染 | config-render 缺键 rc=0 静默 | 渲染后必 grep 产物 |
| 渲染 | PyFoam 写回三副作用 | derive 脚本后处理 |
| 求解 | mpirun 双写者污染 | 起进程前 `ps -C foamRun` 查存量 |
| 求解 | 停跑与存盘相撞 | 等存盘完成再 kill |
