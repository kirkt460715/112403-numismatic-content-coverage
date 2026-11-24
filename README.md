# 講解主題覆蓋分析

本地演練资料记录课程段落版本、历史主题、引用材料来源、材料有效范围和听众反馈。材料与主题为多对多关系，讲解版本只适用于注明的场次。

## Local checks

Python 3.9 or newer is sufficient. The repository has no third-party runtime dependencies.

Run `python3 input_audit.py` to verify the declared files and columns. Run `python3 -m unittest discover -s tests -v` to check the prepared input contract.

The records are synthetic fixtures. Empty values and status labels retain their literal input meaning. The manifest lists file columns and the stable row identifier used by the input audit.
