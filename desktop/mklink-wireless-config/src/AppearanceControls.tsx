import SelectControl from './SelectControl';
import {MoonIcon} from '@phosphor-icons/react/dist/csr/Moon';
import {SunIcon} from '@phosphor-icons/react/dist/csr/Sun';
import {PaletteIcon} from '@phosphor-icons/react/dist/csr/Palette';

export const skins=[{id:'technical',name:'技术青'},{id:'aurora',name:'极光蓝'},{id:'sand',name:'暖砂金'}] as const;
export type Skin=typeof skins[number]['id'];
export function savedSkin():Skin{const value=localStorage.getItem('mklink-skin');return skins.find(s=>s.id===value)?.id??'technical';}

export default function AppearanceControls({theme,skin,onTheme,onSkin}:{theme:string;skin:Skin;onTheme:()=>void;onSkin:(skin:Skin)=>void}){
  return <>
    <SelectControl aria-label="界面皮肤" className="skin-control" value={skin} onValueChange={v=>onSkin(v as Skin)} icon={<PaletteIcon size={20} weight="regular"/>} options={skins.map(s=>({value:s.id,label:s.name}))}/>
    <button className="toolbar-button theme-button" aria-label={`切换到${theme==='dark'?'浅色':'深色'}模式`} onClick={onTheme}>
      {theme==='dark'?<SunIcon size={20} aria-hidden="true"/>:<MoonIcon size={20} aria-hidden="true"/>}
      <span>{theme==='dark'?'浅色模式':'深色模式'}</span>
    </button>
  </>;
}
