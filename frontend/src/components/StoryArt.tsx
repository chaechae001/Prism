import type { Story } from '../api/types';
import { useId } from 'react';

/** Code-native illustration: no third-party news image licensing or remote fetch. */
export function StoryArt({visual,large=false}:{visual:Story['visual'];large?:boolean}){
  const patternId=useId();
  const tech=['chip','research'].includes(visual), city=['city','school','assembly','work'].includes(visual);
  return <div className={`story-art art-${visual} ${large?'art-large':''}`} aria-hidden="true">
    <svg viewBox="0 0 600 340" preserveAspectRatio="xMidYMid slice">
      <defs><pattern id={patternId} width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="currentColor" strokeWidth=".5" opacity=".2"/></pattern></defs>
      <rect width="600" height="340" fill={`url(#${patternId})`}/>
      <circle cx="460" cy="77" r="45" fill="currentColor" opacity=".12"/>
      {tech?<g fill="none" stroke="currentColor" strokeWidth="2">
        <path d="m300 60 140 80v100L300 320 160 240V140Z" opacity=".2"/>
        <path d="m300 86 118 68-118 68-118-68Z" fill="currentColor" fillOpacity=".08"/>
        <path d="m182 154 118 68v73l-118-68Zm118 68 118-68v73l-118 68Z" fill="currentColor" fillOpacity=".17"/>
        {[0,1,2,3,4].map(i=><g key={i} opacity=".5"><path d={`M${208+i*20} ${169+i*12}v40l-30 17M${392-i*20} ${169+i*12}v40l30 17`}/><path d={`M${210+i*22} ${137-i*12}l-38-22M${390-i*22} ${137-i*12}l38-22`}/></g>)}
        <path d="m300 113 70 41-70 41-70-41Z" fill="currentColor" fillOpacity=".75"/>
        <text x="300" y="162" fill="#f5f5ed" stroke="none" textAnchor="middle" fontSize="25" fontFamily="monospace">AI</text>
      </g>:city?<g stroke="currentColor" strokeWidth="1.4" fill="currentColor" fillOpacity=".08">
        <path d="M45 276h510M110 276V154h80v122M202 276V85h108v191M330 276V128h74v148M424 276V182h75v94"/>
        <path d="m202 85 45-26 63 26M330 128l39-24 35 24M110 154l40-21 40 21" fillOpacity=".23"/>
        {[0,1,2,3,4].map(i=><g key={i} fillOpacity=".35" stroke="none"><path d={`M219 ${107+i*28}h14v12h-14ZM249 ${107+i*28}h14v12h-14ZM279 ${107+i*28}h14v12h-14Z`}/></g>)}
        <path d="M127 180h46m-46 24h46m-46 24h46M345 152h44m-44 25h44m-44 25h44M446 204h33m-33 24h33"/>
        <path d="M80 277v-55m0 25c-50-6-33-70 0-66 33-4 50 60 0 66M525 277v-38m0 8c-42-4-26-54 0-50 26-4 42 46 0 50" fillOpacity=".5"/>
      </g>:visual==='energy'?<g stroke="currentColor" strokeWidth="2" fill="currentColor" fillOpacity=".12"><path d="M0 285Q140 220 300 270T600 270"/><path d="M183 270V118m0 0-12-79 22 66m-10 13-73 41 61-53m12 12 62 48-51-60M398 276V153m0 0-12-65 22 54m-10 11-62 34 51-45m11 11 53 40-43-51"/><path d="m250 247 71-28 56 22-71 29Zm56 23v23m-45-41v23m104-31v24"/></g>:<g stroke="currentColor" strokeWidth="2" fill="currentColor" fillOpacity=".16"><path d="M70 276h460M110 253V204h42v49Zm80 0V159h42v94Zm80 0V181h42v72Zm80 0V115h42v138Zm80 0V75h42v178Z"/><path d="m100 166 101-48 86 16L436 42m-48 0h48v48" fill="none" strokeWidth="3"/></g>}
      <text x="25" y="317" fontFamily="monospace" fontSize="11" fill="currentColor" opacity=".55">PRISM / EDITORIAL ILLUSTRATION</text>
    </svg>
  </div>;
}
