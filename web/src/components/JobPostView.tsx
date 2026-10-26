type Props = {
  title: string;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  qualifications: string[];
  min_experience_years: number;
};

export default function JobPostView(job: Props) {
  return (
    <div>
      <h2>{job.title}</h2>
      <p className="muted">
        Minimum experience: {job.min_experience_years} years
      </p>
      <p style={{ whiteSpace: "pre-wrap" }}>{job.description}</p>
      <List title="Required skills" items={job.required_skills} />
      <List title="Nice to have" items={job.preferred_skills} />
      <List title="Qualifications" items={job.qualifications} />
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </>
  );
}