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
 
CREATE TABLE IF NOT EXISTS genres (
    movie_id  INTEGER REFERENCES movies(id),
    name      TEXT NOT NULL
);
 
CREATE TABLE IF NOT EXISTS keywords (
    movie_id  INTEGER REFERENCES movies(id),
    keyword   TEXT NOT NULL
);
 
CREATE TABLE IF NOT EXISTS cast (
    movie_id    INTEGER REFERENCES movies(id),
    name        TEXT NOT NULL,
    character   TEXT,
    cast_order  INTEGER
);
 
CREATE TABLE IF NOT EXISTS crew (
    movie_id  INTEGER REFERENCES movies(id),
    name      TEXT NOT NULL,
    job       TEXT NOT NULL
);
 

-- Support genre filtering, year range queries, and rating sorts without full scans
CREATE INDEX IF NOT EXISTS idx_genres_movie   ON genres(movie_id);
CREATE INDEX IF NOT EXISTS idx_genres_name    ON genres(name);
CREATE INDEX IF NOT EXISTS idx_keywords_movie ON keywords(movie_id);
CREATE INDEX IF NOT EXISTS idx_cast_movie     ON cast(movie_id);
CREATE INDEX IF NOT EXISTS idx_crew_movie     ON crew(movie_id);
CREATE INDEX IF NOT EXISTS idx_movies_year    ON movies(year);
CREATE INDEX IF NOT EXISTS idx_movies_rating  ON movies(vote_average);