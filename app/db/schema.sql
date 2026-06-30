CREATE TABLE IF NOT EXISTS movies (
    id                INTEGER PRIMARY KEY,
    title             TEXT NOT NULL,
    year              INTEGER,
    overview          TEXT,
    tagline           TEXT,
    runtime           INTEGER,
    budget            INTEGER,
    revenue           INTEGER,
    vote_average      REAL,
    vote_count        INTEGER,
    popularity        REAL,
    original_language TEXT
);

-- `cast` is a SQL reserved word. Table is named movie_cast to avoid
-- ambiguity with the CAST() function in generated queries.
CREATE TABLE IF NOT EXISTS genres (
    movie_id  INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    name      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    movie_id  INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    keyword   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS movie_cast (
    movie_id    INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    character   TEXT,
    cast_order  INTEGER
);

CREATE TABLE IF NOT EXISTS crew (
    movie_id  INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    job       TEXT NOT NULL
);


-- Support genre/keyword filtering, name lookups, year ranges, and rating sorts
-- without full scans. cast/crew name and crew.job are indexed because actor and
-- director lookups ("movies with Marlon Brando", "directed by Tarkovsky") are core
-- queries over the largest tables (~100k+ rows).
CREATE INDEX IF NOT EXISTS idx_genres_movie   ON genres(movie_id);
CREATE INDEX IF NOT EXISTS idx_genres_name    ON genres(name);
CREATE INDEX IF NOT EXISTS idx_keywords_movie ON keywords(movie_id);
CREATE INDEX IF NOT EXISTS idx_cast_movie     ON movie_cast(movie_id);
CREATE INDEX IF NOT EXISTS idx_cast_name      ON movie_cast(name);
CREATE INDEX IF NOT EXISTS idx_crew_movie     ON crew(movie_id);
CREATE INDEX IF NOT EXISTS idx_crew_name      ON crew(name);
CREATE INDEX IF NOT EXISTS idx_crew_job       ON crew(job);
CREATE INDEX IF NOT EXISTS idx_movies_year    ON movies(year);
CREATE INDEX IF NOT EXISTS idx_movies_rating  ON movies(vote_average);
