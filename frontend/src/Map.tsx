import { useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, useMap, useMapEvents } from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import type {Endpoint, Route, Station, Point} from './api';
type Props={stations:Station[]; route:Route|null; origin:Endpoint; destination:Endpoint; selecting:'origin'|'destination'|null; onPick:(p:Point)=>void; onStation:(s:Station)=>void};
function Interaction({stations,route,selecting,onPick}:Props){
 const map=useMap();
 useMapEvents({click:e=>{if(selecting)onPick({lat:e.latlng.lat,lon:e.latlng.lng});}});
 useEffect(()=>{if(route){const stops=[route.pickup,route.dropoff].filter(Boolean) as NonNullable<Route['pickup']>[];map.fitBounds(stops.map(s=>[s.lat,s.lon]) as LatLngBoundsExpression,{padding:[100,100],maxZoom:14});}else if(stations.length)map.fitBounds(stations.map(s=>[s.lat,s.lon]) as LatLngBoundsExpression,{padding:[35,35],maxZoom:13});},[route,stations,map]);
 return null;
}
export default function RideMap(props:Props){
 const {stations,route,origin,destination,selecting,onStation}=props;
 const locate=(v:Endpoint)=>typeof v==='string'?stations.find(s=>s.id===v):v;
 const a=locate(origin),b=locate(destination);
 return <MapContainer center={[41.89,-87.65]} zoom={12} className={selecting?'ride-map picking':'ride-map'} scrollWheelZoom>
  <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
  <Interaction {...props}/>
  {stations.map(s=>{const chosen=s.id===route?.pickup?.id||s.id===route?.dropoff.id;return <CircleMarker key={s.id} center={[s.lat,s.lon]} radius={chosen?10:5} pathOptions={{color:chosen?'#fff':'#fff',weight:2,fillColor:chosen?'#174e40':(!s.pickup||s.data_age_seconds>900?'#aaa':s.bikes===0?'#db9157':'#538b78'),fillOpacity:1}} eventHandlers={{click:()=>{if(selecting)props.onPick({lat:s.lat,lon:s.lon});else onStation(s);}}}><Popup><strong>{s.name}</strong><br/>{s.bikes} bikes · {s.docks} docks<br/>Snapshot {s.data_age_seconds}s old</Popup></CircleMarker>;})}
  {route&&<>
   {route.pickup&&a&&<Polyline positions={[[a.lat,a.lon],[route.pickup.lat,route.pickup.lon]]} pathOptions={{color:'#538b78',dashArray:'5 7',weight:3}}/>}
   {route.pickup&&<Polyline positions={[[route.pickup.lat,route.pickup.lon],[route.dropoff.lat,route.dropoff.lon]]} pathOptions={{color:'#174e40',weight:5,opacity:.85}}/>}
   {b&&<Polyline positions={[[route.dropoff.lat,route.dropoff.lon],[b.lat,b.lon]]} pathOptions={{color:'#538b78',dashArray:'5 7',weight:3}}/>}
  </>}
  {[a,b].map((p,i)=>p&&<CircleMarker key={i} center={[p.lat,p.lon]} radius={7} pathOptions={{color:'#fff',weight:3,fillColor:i?'#d78b54':'#343e38',fillOpacity:1}}><Popup>{i?'Destination':'Origin'}</Popup></CircleMarker>)}
 </MapContainer>;
}
