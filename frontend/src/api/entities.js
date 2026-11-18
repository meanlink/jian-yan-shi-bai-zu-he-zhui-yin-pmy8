import {api} from './client.js';
export const datasets={
  list:()=>api('/datasets'),
  get:id=>api('/datasets/'+id),
  create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)}),
  createLegacy:data=>api('/datasets/legacy',{method:'POST',body:JSON.stringify(data)}),
  createVersion:(id,data)=>api('/datasets/'+id+'/versions',{method:'POST',body:JSON.stringify(data)}),
};
export const jobs={
  list:()=>api('/jobs'),
  get:id=>api('/jobs/'+id),
  create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),
  approve:id=>api('/jobs/'+id+'/approve',{method:'POST'}),
  judgments:id=>api('/jobs/'+id+'/judgments'),
};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
