/* View preferences and lightweight motion. No external requests or account writes. */
'use strict';
(() => {
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let motion=true;
  try{motion=localStorage.getItem('sonaria.motion')!=='off';}catch(_){}
  const canMove=()=>motion&&!reduced.matches;
  function applyMotion(){
    document.documentElement.dataset.motion=canMove()?'on':'off';
    const button=$('motion-toggle');button.setAttribute('aria-pressed',String(canMove()));
    button.textContent=reduced.matches?'✦ Movimento reduzido':motion?'✦ Animações ligadas':'✦ Animações desligadas';
    if(!canMove())document.getAnimations().forEach(a=>a.cancel());
  }
  reduced.addEventListener('change',applyMotion);applyMotion();
  $('motion-toggle').addEventListener('click',()=>{motion=!motion;try{localStorage.setItem('sonaria.motion',motion?'on':'off');}catch(_){}applyMotion();});
  let layout='cards';try{layout=localStorage.getItem('sonaria.layout')==='list'?'list':'cards';}catch(_){}
  function setLayout(next){
    layout=next;$('listings').dataset.layout=layout;
    for(const kind of ['cards','list']){
      const button=$('view-'+kind),active=kind===layout;
      button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    }
    try{localStorage.setItem('sonaria.layout',layout);}catch(_){}
  }
  setLayout(layout);
  $('view-cards').addEventListener('click',()=>setLayout('cards'));
  $('view-list').addEventListener('click',()=>setLayout('list'));
  $('filter-ready').addEventListener('click',()=>{onlyReady=!onlyReady;$('filter-ready').setAttribute('aria-pressed',String(onlyReady));renderListings();});
  $('nav-schedules').addEventListener('click',()=>{navigate('routines');$('sidebar').classList.remove('open');});
  $('nav-inbox').addEventListener('click',()=>{openInbox();$('sidebar').classList.remove('open');});
  document.querySelectorAll('.nav-item').forEach(el=>{el.setAttribute('aria-label',el.textContent.trim());el.title=el.textContent.trim();});
  document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>{
    if(el.dataset.page==='market')switchMarketTab('listings');
    $('sidebar').classList.remove('open');updateDeskNavigation();
  }));
  document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();navigate('market');switchMarketTab('listings');});
  document.addEventListener('click',e=>{
    if($('sidebar').classList.contains('open')&&!e.target.closest('#sidebar,#menu-toggle'))$('sidebar').classList.remove('open');
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape')$('sidebar').classList.remove('open');
    if(e.defaultPrevented||e.ctrlKey||e.metaKey||e.altKey||e.target.closest('input,textarea,select,[contenteditable=true]')||document.querySelector('.modal-backdrop:not(.hidden)'))return;
    if(e.key==='/'){e.preventDefault();navigate('market');switchMarketTab('listings');$('listfilter').focus();}
    if(e.key.toLowerCase()==='n'){e.preventDefault();openEditor();}
  });
  document.addEventListener('pointerdown',e=>{
    if(!canMove()||e.pointerType==='touch')return;
    const button=e.target.closest('button');if(!button||button.disabled||button.querySelector('.studio-ripple'))return;
    const bounds=button.getBoundingClientRect(),ripple=document.createElement('span');
    ripple.className='studio-ripple';ripple.setAttribute('aria-hidden','true');
    ripple.style.left=(e.clientX-bounds.left)+'px';ripple.style.top=(e.clientY-bounds.top)+'px';
    button.append(ripple);ripple.addEventListener('animationend',()=>ripple.remove(),{once:true});
    setTimeout(()=>ripple.remove(),800);
  });
  let lightFrame=0,lightTarget=null,lightX=0,lightY=0;
  document.addEventListener('pointermove',e=>{
    if(!canMove()||e.pointerType==='touch')return;
    const card=e.target.closest('.listing-card');if(!card)return;
    lightTarget=card;lightX=e.clientX;lightY=e.clientY;
    if(lightFrame)return;
    lightFrame=requestAnimationFrame(()=>{
      lightFrame=0;if(!lightTarget?.isConnected||!canMove())return;
      const box=lightTarget.getBoundingClientRect();
      lightTarget.style.setProperty('--pointer-x',(lightX-box.left)+'px');
      lightTarget.style.setProperty('--pointer-y',(lightY-box.top)+'px');
    });
  },{passive:true});
  const seenCards=new Set();
  function revealCards(){
    let index=0;
    document.querySelectorAll('.listing-card').forEach(card=>{
      const key=card.dataset.cardOffers;
      if(seenCards.has(key))return;seenCards.add(key);
      if(canMove()&&index<12)card.animate([{opacity:0,transform:'translateY(14px)'},{opacity:1,transform:'translateY(0)'}],{duration:440,delay:Math.min(index++,5)*45,easing:'cubic-bezier(.2,.8,.2,1)',fill:'backwards'});
    });
  }
  new MutationObserver(revealCards).observe($('listings'),{childList:true,subtree:true});
  document.querySelectorAll('.desk-metric strong').forEach(el=>el.addEventListener('desk-value',()=>{
    if(canMove())el.animate([{opacity:.35,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],{duration:280,easing:'ease-out'});
  }));
  updateDeskOverview();updateDeskNavigation();revealCards();
})();
