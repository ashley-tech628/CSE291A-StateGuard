import json
from pathlib import Path
import matplotlib.pyplot as plt
p=Path('paper/phase1/figures'); d=json.loads(Path('results/c-phase1-llm-matched-summary.json').read_text()); rows=list(d['policies'].values())
with plt.rc_context({'font.size':8,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False}):
 f,ax=plt.subplots(1,2,figsize=(3.35,1.55))
 for a,vals,title in [(ax[0],[100*r['fault_success']/r['matched_pairs'] for r in rows],'Task completion (%)'),(ax[1],[r['actual_tokens_fault']/r['matched_pairs'] for r in rows],'Tokens / fault run')]:
  a.bar(['NR','FR','AV'],vals,color=['#8A939B','#18758A','#BB945A'],width=.62); a.set_title(title,fontsize=7.5); a.tick_params(labelsize=7); a.grid(axis='y',lw=.4,alpha=.2); a.set_axisbelow(True)
 f.subplots_adjust(left=.12,right=.99,bottom=.20,top=.80,wspace=.55)
 f.savefig(p/'overview.pdf',bbox_inches='tight',pad_inches=.02); f.savefig(p/'overview.png',dpi=300,bbox_inches='tight',pad_inches=.02)
