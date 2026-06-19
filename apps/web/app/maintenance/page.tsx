'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, PageHeader } from '../../components/ui';

export default function MaintenanceRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/sources'); }, [router]);
  return <main className="page"><PageHeader eyebrow="Sources" title="Maintenance moved to Sources" description="Source refresh and lifecycle actions now belong with Sources." /><Card><p className="muted">Redirecting to Sources…</p></Card></main>;
}
