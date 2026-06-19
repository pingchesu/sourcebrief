'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, PageHeader } from '../../components/ui';

export default function AgentFilesRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/agent-profile'); }, [router]);
  return <main className="page"><PageHeader eyebrow="Project agent" title="Agent delivery moved" description="Agent delivery is now part of the Project Agent page." /><Card><p className="muted">Redirecting to Project Agent…</p></Card></main>;
}
