/** Layout-only paragraph grouping. Never summarize or rewrite the source text. */
export function articleParagraphs(text:string):string[] {
  const blocks=text.replace(/\r\n?/g,'\n').trim().split(/\n+/).map(s=>s.trim()).filter(Boolean);
  const paragraphs:string[]=[];
  for(const block of blocks){
    const sentences=block.split(/(?<=[.!?。！？])\s+(?=\S)/u);
    let current='';let count=0;
    for(const sentence of sentences){
      if(current&&(current.length>=150||count>=3)){paragraphs.push(current);current='';count=0;}
      current+=(current?' ':'')+sentence;count++;
    }
    if(current) paragraphs.push(current);
  }
  return paragraphs;
}
