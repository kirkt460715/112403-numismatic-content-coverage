# 钱币文化课程内容覆盖分析工具

本地、无第三方运行时依赖的内容覆盖与修订影响工具。它把**段落、历史主题、关系类型、引用材料、来源状态/有效期、讲解时长和课堂反馈**连成语义链，帮助教研人员判断：

- 哪些必需主题仍是缺口；
- 哪些段落只是介绍外形或重复例证，没有解释货币、信用与地方经济的关系；
- 主题结论有哪些独立、可用、可信的材料支持；
- 低理解率反馈出现在哪里；
- 来源撤下、来源说明更正、课程拆段/合段或新增段落后，哪些结论和已采纳建议需要复核；
- 委员会讨论时，如何从一条主题结论追到具体 reference、source、课程版本和输入文件指纹。

## 1. 快速开始

需要 Python 3.9+。

```bash
# 校验 manifest 声明的列、主键和合成输入
python3 input_audit.py
python3 -m coverage_tool validate --data data

# 也可使用根目录便捷入口
python3 analyze.py validate

# 生成当前最新课程版本的 Markdown + JSON 报告
python3 main.py
# 或显式指定观察日和听众年龄
python3 -m coverage_tool analyze \
  --data data \
  --as-of 2026-11-24 \
  --audience-age 12 \
  --out reports

# 等价入口
python3 analyze.py analyze --as-of 2026-11-24 --audience-age 12
```

产物：

- `reports/coverage-report.md`：最新版本（当前合成数据为 C2）的教研会/馆藏复核报告；
- `reports/coverage-report-C1.md`：用 C1 场次时点 `2026-09-15` 生成的历史版本示例；
- 同名 `.json`：供后续工具或委员会系统处理，包含完整输入快照与哈希。

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 2. 每轮修订的推荐流程

### 2.1 讨论前：生成不可变快照

```bash
python3 -m coverage_tool snapshot \
  --version C1 \
  --as-of 2026-09-15 \
  --out snapshots
```

快照 JSON 保存当时所有 CSV 行、文件名和 SHA-256 指纹。会后即使 CSV 被修改，委员仍可从快照还原“当时实际使用的材料和讲述版本”。

### 2.2 记录已经采纳的教学建议

```bash
python3 -m coverage_tool adopt \
  --id R-2026-001 \
  --text "为票号信用补一条独立权威来源，并解释汇兑与地方贸易" \
  --topic T4 \
  --segment G05 \
  --version C2 \
  --reference-ids L5 \
  --as-of 2026-11-24
```

默认写入 `state/adopted_recommendations.json`。工具会保存所引来源的 `source_note` 哈希和整行哈希。也支持直接维护：

- `data/adopted_recommendations.csv`，或
- `data/recommendations.csv`。

CSV 中多个 `source_ids` / `reference_ids` 可用分号或逗号分隔。

### 2.3 修改讲稿和资料

- 新增段落：向 `segments.csv` 增加新的稳定 `segment_id`，并在 `segment_topics.csv` 标注主题关系；下次分析会自动纳入。
- 拆段/合段：**不要复用或改写旧 segment_id 的历史含义**。旧反馈继续保留旧 ID；新段落使用新 ID。可选择添加 `data/segment_lineage.csv`：

```csv
old_segment_id,new_segment_id,relation_type,effective_from,note
G03,G06,split,2026-10-01,尖足布分型拆为新段
G04,G07,merge_target,2026-10-01,两段合并示例
```

工具只显示谱系提示，**不会把旧反馈自动改挂到新段落**。

- 新场次有明确日期时，可添加可选 `data/sessions.csv`：

```csv
session_id,session_date,course_version
S1,2026-09-10,C1
S2,2026-11-05,C2
```

没有场次日期时，工具会保留全部有效期记录并明确标注无法唯一判断“当日生效关系”，而不是猜测。

### 2.4 来源撤下或更正后：比较基线快照

```bash
# 馆藏更正 source_note、修改 review_status 或 available_to 后
python3 -m coverage_tool impact \
  --baseline snapshots/snapshot-2026-11-24-xxxxxxxx.json \
  --data data \
  --as-of 2026-11-24 \
  --out reports
```

影响报告：

1. 列出来源字段变化；
2. 经 `references.csv` 找到受影响 reference、segment、主题和课程版本；
3. 用当前剩余材料重新计算证据等级；
4. 复核所有引用该来源/reference 的已采纳建议。

如果另一个独立可信来源仍足以支持主题，主题不会被一并判为无效；但直接基于被更正/撤下来源的教学建议仍会标记为 `affected_needs_revalidation...`，因为来源原文或适用范围已经变化。

## 3. 覆盖是怎样判定的

工具不把段落数量当作覆盖充分性。每个主题分别计算三个维度：

### 3.1 讲述状态

由 `segment_topics.relation` 判定，支持英文和常见中文标签：

- `explains / analyzes / connects / 解释 / 分析 / 因果 / 联系`：解释性、关联性关系；
- `introduces / context / example / describes / 介绍 / 背景 / 例证 / 外形描述`：浅层、描述或重复风险；
- 空值或未知值：保留原值并标为未分类，不擅自提升为“解释”。

若同一主题在多个段落只有介绍、背景、例证或外形描述，而没有解释/分析关系，会给出 `shallow_repetition` 警告。

### 3.2 证据强度

`references.claim_topic` 必须精确匹配 `topics.topic_id` 或 `topics.label`，才计为该主题的直接证据。像 `claim_topic=地方货币` 与主题标签 `地方金融` 不完全一致时，不会被静默等同，而会进入“需馆藏复核的叙述范围”。

证据等级：

- `strong`：至少两个相互独立、可用且达到中/高可信层的来源，且通常含高可信来源；
- `moderate`：一个 `approved/verified` 高可信来源，或两个中等可信独立来源；可支持结论；
- `provisional`：只有 `review/pending/待审核` 来源；
- `weak` / `unrated`：低可信或缺少评级；
- `none`：没有精确映射的直接引用；
- `lapsed_or_withdrawn`：引用存在，但来源被撤下/驳回或不在授权有效期。

同一 `source_id` 的多条引用不会被算成多个独立来源。

### 3.3 总体覆盖类别

常见结论包括：

- `strong_coverage` / `covered`；
- `explanation_depth_gap`：有材料和讲述，但缺因果/联系解释；
- `evidence_limited` / `evidence_gap`；
- `needs_depth_and_evidence`；
- `annotation_gap`：反馈或段落显示讲过，但缺少规范主题标注；
- `gap`：必需主题没有段落安排。

## 4. 来源可信度与适合年龄

基础表保留输入中的 `review_status` 原值，不把空状态或 `review` 默认成 `approved`。已知状态会映射为 high / medium / provisional / blocked；未知状态保留为 `unrated_status`。

当前合成 `sources.csv` 没有年龄列。工具会如实输出未分级状态，不会把“未分级”当作“全年龄”。仓库提供了可选覆盖表 `data/source_profiles.csv`（演练值，正式使用时应由馆藏/教研替换）：

```csv
source_id,trust_tier,min_age,handling_note
A1,high,10,教师引导
A2,provisional,14,尚待馆藏审核且需年龄改写
```

`config/source_profiles.example.csv` 是同样的示例。若要直接在 `sources.csv` 增加 `trust_tier`、`min_age` 或 `age_rating` 列，请同步更新 `data/manifest.json` 的列契约；分析器已能读取这些字段。年龄限制只影响年龄适配提示，不改变历史证据强度。

## 5. 连续课程脉络与讲述顺序

`config/curriculum_blueprint.json` 保存中心要求的连续课程脉络：先秦贝币、刀布币/晋阳尖足布、秦汉币制、唐代通宝、宋代交子、晋商票号，以及“货币—信用—地方经济”跨时期联系。

蓝图关键词只用于发现文本信号，不会自动把宽泛主题认定为具体知识点：

- `explicitly_scheduled_with_text_signal`：有明确主题且有关键词；
- `explicit_broad_topic_verify_specifics`：只有宽泛主题，需核实是否真的讲到贝币、刀布等细节；
- `keyword_signal_requires_topic_tag`：标题/叙述有关键词，但需补规范主题；
- `gap`：没有主题或文本信号。

顺序检查包括 position 重复/断号、年代回跳和多段浅层重复。例如合成 C1 中 `G02 秦汉币制 → G03 晋阳尖足布` 会提示年代回跳；若 G03 是有意设置的地方专题，应在讲稿中加入回旋/过渡说明。

## 6. 反馈的边界

反馈按 `session_id + segment_id + topic_id` 保存，并计算理解率和 Wilson 95% 区间，以提示小样本不确定性。

反馈只回答“听众是否理解”，**不回答“历史解释是否可靠”**。因此：

- 高理解率不会提升证据等级；
- 低理解率会进入教研修订建议；
- 反馈始终关联当时的稳定 segment_id；
- 拆段/合段后不按热度或位置自动迁移。

## 7. 编程接口

```python
from coverage_tool import analyze_coverage, compare_revisions, render_markdown

analysis = analyze_coverage(
    "data",
    course_version="C2",
    as_of="2026-11-24",
    audience_age=12,
    blueprint_path="config/curriculum_blueprint.json",
)
print(render_markdown(analysis))

baseline = analysis  # 或读取以前生成的 coverage-report.json / snapshot JSON
impact = compare_revisions(baseline, current_repo)
```

## 8. 输入契约说明

`data/manifest.json` 声明六张核心表。`segment_topics` 是多对多时态关系，因此使用组合唯一键 `(segment_id, topic_id, valid_from)`；同一主题可由多材料说明，同一材料也可经多条 reference 支撑不同 `claim_topic`。

空 `valid_to` / `available_to` 表示开放区间；空审核状态保留为空状态并触发警告。所有记录均为合成演练数据。
