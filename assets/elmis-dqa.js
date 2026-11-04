(function (root) {
  'use strict';
  const statuses = {active:'Active',limited:'Limited / irregular',inactive:'Not used',unavailable:'Unable to verify'};
  const commodities = {dmpa_sc:'DMPA-SC / Sayana Press',dmpa_im:'DMPA-IM / Depo-Provera',coc:'Combined oral contraceptive pills',implanon:'Implanon NXT',jadelle:'Jadelle',iucd:'IUCD',other:'Other RH commodity'};
  const numeric = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
  const yes = v => v === 'yes';
  const isDate = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v));
  function validateDataset(data) {
    if (!data || data.schemaVersion !== 1 || data.round !== 'round4' || !Array.isArray(data.records)) throw new Error('Unsupported eLMIS assessment dataset.');
    const ids = new Set();
    for (const r of data.records) {
      if (!r.id || ids.has(String(r.id)) || !isDate(r.visitDate) || !r.facility || !r.province || !r.district) throw new Error('Each assessment needs a unique ID, visit date and facility location.');
      ids.add(String(r.id));
      if (!Array.isArray(r.issues) || !Array.isArray(r.commodities) || !Array.isArray(r.stockouts)) throw new Error('Assessment repeat records are missing.');
      if (r.stockouts.some(v => ['none','not_verified'].includes(v)) && r.stockouts.length !== 1) throw new Error('None and Not verified must be exclusive stock-out answers.');
    }
    return data;
  }
  function latestVisits(records) {
    const latest = new Map();
    for (const r of records) {
      const key = r.facilityId ? `id:${r.facilityId}` : [r.province,r.district,r.facility].join('|');
      const old = latest.get(key);
      if (!old || `${r.visitDate}|${r.submittedAt || ''}|${r.id}` > `${old.visitDate}|${old.submittedAt || ''}|${old.id}`) latest.set(key,r);
    }
    return [...latest.values()];
  }
  function summarize(records, today = new Date().toISOString().slice(0,10)) {
    const issues = records.flatMap(r => r.issues.map(i => ({...i,facility:r.facility})));
    const stock = records.flatMap(r => r.commodities.map(c => ({...c,facility:r.facility})));
    const valid = stock.filter(c => yes(c.basisConfirmed) && c.unit && c.cutoff);
    const before = valid.filter(c => numeric(c.physicalBefore) && numeric(c.elmisBefore));
    const after = valid.filter(c => numeric(c.physicalAfter) && numeric(c.elmisAfter));
    const ojt = records.filter(r => yes(r.ojtDone));
    const competent = ojt.filter(r => numeric(r.staffMentored) && numeric(r.staffCompetent) && r.staffCompetent <= r.staffMentored);
    const stockoutReported = records.filter(r => r.stockouts.length && !r.stockouts.includes('not_verified'));
    const open = issues.filter(i => ['partial','escalated','pending','not_resolved'].includes(i.status));
    return {
      records,issues,stock,total:records.length,
      accessKnown:records.filter(r => ['yes','no'].includes(r.accessible)).length,
      accessible:records.filter(r => yes(r.accessible)).length,
      utilization:Object.fromEntries(Object.keys(statuses).map(k => [k,records.filter(r => r.utilization === k).length])),
      ojt:ojt.length,mentored:competent.reduce((n,r)=>n+r.staffMentored,0),competent:competent.reduce((n,r)=>n+r.staffCompetent,0),competencyVisits:competent.length,
      open:open.length,resolved:issues.filter(i=>i.status==='resolved').length,
      overdue:open.filter(i=>isDate(i.deadline)&&i.deadline<today).length,
      missingOwner:open.filter(i=>i.hasOwner!==true).length,
      stockoutKnown:stockoutReported.length,
      stockoutFacilities:stockoutReported.filter(r=>r.stockouts.some(c=>!['none','not_verified'].includes(c))).length,
      stockouts:Object.fromEntries(Object.keys(commodities).map(k=>[k,stockoutReported.filter(r=>r.stockouts.includes(k)).length])),
      beforeTotal:before.length,beforeMatch:before.filter(c=>c.physicalBefore===c.elmisBefore).length,
      afterTotal:after.length,afterMatch:after.filter(c=>c.physicalAfter===c.elmisAfter).length
    };
  }
  const api = {validateDataset,latestVisits,summarize};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ElmisDqa = api;
  if (typeof document === 'undefined') return;
  const dataSource = document.querySelector('script[data-elmis-source]')?.dataset.elmisSource || 'data/round4/elmis.json';
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const empty = text => `<div class="empty"><strong>No assessment results yet</strong>${esc(text)}</div>`;
  const fraction = (n,d) => d ? `${n}/${d} (${Math.round(n/d*100)}%)` : 'Not available';
  const metric = (label,value,detail) => `<article class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><span>${esc(detail)}</span></article>`;
  const line = (label,value) => `<div class="line"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
  const answer = v => v==='yes'?'Yes':v==='no'?'No':'Not recorded';
  let dataset = {records:[]};
  function options(id,values,label) {
    const select=$(id),previous=select.value;
    select.replaceChildren(new Option(label,''),...values.filter(Boolean).sort().map(v=>new Option(v,v)));
    if ([...select.options].some(o=>o.value===previous)) select.value=previous;
  }
  function baseFiltered() {
    return dataset.records.filter(r=>(!$('province').value||r.province===$('province').value)&&(!$('district').value||r.district===$('district').value)&&(!$('visitDate').value||r.visitDate===$('visitDate').value));
  }
  function render() {
    const visits=baseFiltered();
    const records=latestVisits(visits).filter(r=>(!$('utilization').value||r.utilization===$('utilization').value)&&r.facility.toLowerCase().includes($('facilitySearch').value.trim().toLowerCase()));
    const dateParts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Lusaka',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(p=>[p.type,p.value]));
    const m=summarize(records,`${dateParts.year}-${dateParts.month}-${dateParts.day}`);
    const pending=dataset.records.length===0;
    $('scope').textContent=pending?'Ready for eLMIS DQA results. No assessments or targets have been published.':`${records.length} facilities shown · ${visits.length} visits in the selected date/location scope · latest visit per facility. No target denominator is configured.`;
    $('metrics').innerHTML=metric('Facilities assessed',pending?'—':m.total,pending?'Awaiting submissions':'Latest visits in current view')+metric('eLMIS accessible',fraction(m.accessible,m.accessKnown),'Among facilities with a recorded access answer')+metric('OJT conducted',m.total?m.ojt:'—','Facilities reporting on-the-job training')+metric('Facilities with stock-outs',fraction(m.stockoutFacilities,m.stockoutKnown),'Among verified stock-out responses');
    $('utilizationSummary').innerHTML=m.total?Object.entries(statuses).map(([k,label])=>line(label,m.utilization[k])).join(''):empty('Utilization results will appear after assessment import.');
    $('mentorshipSummary').innerHTML=m.total?line('Staff mentored',m.competencyVisits?m.mentored:'Not recorded')+line('Demonstrated competency',fraction(m.competent,m.mentored))+line('Visits with complete competency counts',m.competencyVisits):empty('Mentoring and independent competency checks will appear here.');
    $('facilityRows').innerHTML=records.length?records.map(r=>`<tr><td>${esc(r.province)}<small>${esc(r.district)}</small></td><td>${esc(r.facility)}</td><td>${esc(r.visitDate)}</td><td>${answer(r.accessible)}</td><td><span class="pill">${esc(statuses[r.utilization]||'Not recorded')}</span></td><td>${answer(r.ojtDone)}</td><td>${esc(r.stockouts.map(k=>commodities[k]||(k==='none'?'None':k==='not_verified'?'Not verified':k)).join(', ')||'Not recorded')}</td></tr>`).join(''):'<tr><td colspan="7">No facility assessments in this view.</td></tr>';
    $('issueSummary').innerHTML=metric('Resolved',m.total?m.resolved:'—','Verified resolution status')+metric('Open issues',m.total?m.open:'—','Partial, escalated, pending or unresolved')+metric('Overdue open issues',m.total?m.overdue:'—','Deadline before today in Zambia')+metric('Open issues without owner',m.total?m.missingOwner:'—','Named accountable person not recorded');
    $('issueRows').innerHTML=m.issues.length?m.issues.map(i=>`<tr><td>${esc(i.facility)}</td><td>${esc(i.category||'Not recorded')}</td><td>${esc(i.status||'Not recorded')}</td><td>${i.hasOwner?'Yes':'Not recorded'}</td><td>${esc(i.deadline||'Not recorded')}</td><td>${esc(i.followupOutcome||'Not recorded')}</td></tr>`).join(''):'<tr><td colspan="6">No issue records in this view.</td></tr>';
    $('stockoutSummary').innerHTML=m.stockoutKnown?Object.entries(commodities).map(([k,label])=>line(label,m.stockouts[k])).join('')+line('Facilities with verified responses',m.stockoutKnown):empty('Stock-out selections will be counted independently of eLMIS access.');
    $('stockSummary').innerHTML=line('Sampled commodity records',m.total?m.stock.length:'—')+line('Matching before intervention',fraction(m.beforeMatch,m.beforeTotal))+line('Matching after intervention',fraction(m.afterMatch,m.afterTotal));
    const variance=(a,b)=>numeric(a)&&numeric(b)?a-b:'Not available';
    $('commodityRows').innerHTML=m.stock.length?m.stock.map(c=>`<tr><td>${esc(c.facility)}<small>${esc(commodities[c.commodity]||c.commodity||'Not recorded')}</small></td><td>${esc(c.unit||'Not recorded')}</td><td>${esc(yes(c.basisConfirmed)?variance(c.physicalBefore,c.elmisBefore):'Not comparable')}</td><td>${esc(yes(c.basisConfirmed)?variance(c.physicalAfter,c.elmisAfter):'Not comparable')}</td><td>${yes(c.basisConfirmed)?'Confirmed':'Not confirmed'}<small>${esc(c.cutoff||'Cutoff not recorded')}</small></td></tr>`).join(''):'<tr><td colspan="5">No RH commodity verification records in this view.</td></tr>';
  }
  async function init() {
    try {
      const response=await fetch(dataSource,{cache:'no-store'});
      if (!response.ok) throw new Error(`Assessment file unavailable (${response.status}).`);
      dataset=validateDataset(await response.json());
      $('dataStatus').textContent=dataset.records.length?'Assessment results available':'Awaiting assessment results';
      $('updated').textContent=dataset.updatedAt?`Dataset updated: ${dataset.updatedAt}`:'Prepared for results · No submissions loaded';
      options('province',[...new Set(dataset.records.map(r=>r.province))],'All provinces');
      options('district',[...new Set(dataset.records.map(r=>r.district))],'All districts');
      options('visitDate',[...new Set(dataset.records.map(r=>r.visitDate))],'All dates');
      for(const id of ['province','district','visitDate','utilization']) $(id).addEventListener('change',()=>{
        if(id==='province') {$('district').value='';options('district',[...new Set(dataset.records.filter(r=>!$('province').value||r.province===$('province').value).map(r=>r.district))],'All districts');}
        render();
      });
      $('facilitySearch').addEventListener('input',render);
      $('resetFilters').addEventListener('click',()=>{for(const id of ['province','district','visitDate','utilization','facilitySearch'])$(id).value='';options('district',[...new Set(dataset.records.map(r=>r.district))],'All districts');render();});
      render();
    } catch(error) {
      $('dataStatus').textContent='Assessment data could not be loaded';
      $('scope').textContent=error.message;
      $('metrics').innerHTML=empty('Reload the page. If the problem persists, check the published assessment file.');
    }
  }
  init();
})(typeof globalThis!=='undefined'?globalThis:this);
