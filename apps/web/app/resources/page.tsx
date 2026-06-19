import { redirect } from 'next/navigation';

// Sources lifecycle was consolidated into the canonical /sources hub (PR2).
// Keep this route reachable so existing links/bookmarks do not 404.
export default function ResourcesRedirect() {
  redirect('/sources');
}
