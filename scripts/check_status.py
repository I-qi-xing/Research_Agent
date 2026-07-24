import os

papers_dir = "./papers"
analysis_dir = "./analysis"
review_dir = "./review"
output_dir = "./output"

pdf_count = len([f for f in os.listdir(papers_dir) if f.lower().endswith(".pdf")])

raw_count = 0
md_count = 0
if os.path.isdir(analysis_dir):
    for f in os.listdir(analysis_dir):
        if f.endswith("_raw.txt"):
            raw_count += 1
        elif f.endswith("_analysis.md"):
            md_count += 1

syn_report = os.path.join(review_dir, "synthesis_report.md")
syn_exists = os.path.isfile(syn_report)

opp_report = os.path.join(output_dir, "research_opportunities.md")
opp_exists = os.path.isfile(opp_report)

print("=" * 50)
print("         Research Agent - Project Status")
print("=" * 50)
print(f"  papers/  : {pdf_count} PDF(s)")
print(f"  analysis/: {raw_count} _raw.txt, {md_count} _analysis.md")
print(f"  review/  : synthesis_report.md  {'[OK]' if syn_exists else '[MISSING]'}")
print(f"  output/  : research_opportunities.md {'[OK]' if opp_exists else '[MISSING]'}")
print("=" * 50)
