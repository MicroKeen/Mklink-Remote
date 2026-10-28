import type {ReactNode} from 'react';
import * as Select from '@radix-ui/react-select';
import {CaretDownIcon} from '@phosphor-icons/react/dist/csr/CaretDown';
import {CaretUpIcon} from '@phosphor-icons/react/dist/csr/CaretUp';
import {CheckIcon} from '@phosphor-icons/react/dist/csr/Check';
import './select.css';

type Option={value:string;label:string;disabled?:boolean};
type Props={
  id?:string;
  'aria-label'?:string;
  value:string;
  onValueChange:(value:string)=>void;
  options:readonly Option[];
  placeholder?:string;
  disabled?:boolean;
  className?:string;
  icon?:ReactNode;
};

/** One styled control for every desktop selector; Radix owns focus and keyboard behavior. */
export default function SelectControl({id,'aria-label':label,value,onValueChange,options,placeholder='请选择',disabled=false,className='',icon}:Props){
  const selected=options.find(option=>option.value===value);
  return <Select.Root value={selected?value:''} onValueChange={onValueChange} disabled={disabled||!options.length}>
    <Select.Trigger id={id} aria-label={label} className={`ui-select-trigger ${className}`} title={selected?.label??placeholder}>
      {icon&&<span className="ui-select-leading" aria-hidden="true">{icon}</span>}
      <span className="ui-select-value"><Select.Value placeholder={placeholder}/></span>
      <Select.Icon className="ui-select-caret"><CaretDownIcon size={18} aria-hidden="true"/></Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Content className="ui-select-menu" position="popper" sideOffset={6} collisionPadding={12}>
        <Select.ScrollUpButton className="ui-select-scroll"><CaretUpIcon size={18}/></Select.ScrollUpButton>
        <Select.Viewport className="ui-select-viewport">
          {options.map(option=><Select.Item key={option.value} value={option.value} disabled={option.disabled} textValue={option.label} className="ui-select-option" title={option.label}>
            <Select.ItemText>{option.label}</Select.ItemText>
            <Select.ItemIndicator className="ui-select-check"><CheckIcon size={18} weight="bold"/></Select.ItemIndicator>
          </Select.Item>)}
        </Select.Viewport>
        <Select.ScrollDownButton className="ui-select-scroll"><CaretDownIcon size={18}/></Select.ScrollDownButton>
      </Select.Content>
    </Select.Portal>
  </Select.Root>;
}
