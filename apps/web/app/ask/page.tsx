import { redirect } from 'next/navigation';

// Ask / citations / context preview were consolidated into the canonical
// /workbench hub (PR3). Keep this route reachable so existing links/bookmarks
// do not 404.
export default function AskRedirect() {
  redirect('/workbench');
}
