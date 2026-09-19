import {
  AirplaneTilt, ArrowsLeftRight, Bank, Briefcase, Car, CreditCard, DotsThree, FilmSlate, ForkKnife,
  HandHeart, Heartbeat, House, Lightning, Money, Repeat, ShieldCheck, ShoppingBag, ShoppingCart, TrendUp,
  Warning, Wrench, type Icon,
} from '@phosphor-icons/react'

const ICONS: Record<string, Icon> = {
  AirplaneTilt, ArrowsLeftRight, Bank, Briefcase, Car, CreditCard, DotsThree, FilmSlate, ForkKnife,
  HandHeart, Heartbeat, House, Lightning, Money, Repeat, ShieldCheck, ShoppingBag, ShoppingCart, TrendUp,
  Warning, Wrench,
}

export function CategoryIcon({ name, size = 18, className }: { name: string; size?: number; className?: string }) {
  const C = ICONS[name] ?? DotsThree
  return <C size={size} weight="regular" className={className} />
}
